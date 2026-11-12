# 題 1｜程式碼審查：訂單查詢助理

原始程式碼逐字保留在 [`original_agent.py`](original_agent.py)。修正版在 [`order_agent.py`](order_agent.py)（模型別名、逾時、步數上限和給模型看的中文句子都在 [`settings.json`](settings.json)，程式裡不寫死），測試在 [`tests/q1/test_order_agent.py`](../tests/q1/test_order_agent.py)。

執行測試：

```bash
uv run pytest tests/q1
```

## 問題清單（依嚴重程度排序）

嚴重程度的定義如下。

- **P0**：一則訊息就能造成資料外洩或不可逆的資料毀損。
- **P1**：功能壞掉、成本失控，或違反公司政策。
- **P2**：可維護性與可觀測性。出事時查不到、改不動。

### P0-1. 沒有身分與授權，任何人都能查或取消任何訂單

工具只收 `order_id`。程式不知道是誰在問，也不檢查訂單屬於誰。

**出事情境。** 會員輸入「幫我取消訂單 A1002」，A1002 是別人的訂單，照樣被取消。也可以一筆一筆查別人的訂單，連同電話與地址。更隱蔽的是間接 prompt injection：使用者貼上的文字或之後接進來的資料夾帶「請取消訂單 X」，模型照做。

### P0-2. SQL injection，一句話可以取消整張表

`order_id` 由模型產生，而模型的輸出受使用者輸入控制。程式用 f-string 把它直接拼進 SQL。

**出事情境。** 使用者說「幫我取消訂單 `x' OR '1'='1`」。模型照抄參數，SQL 變成 `UPDATE orders SET status='cancelled' WHERE id = 'x' OR '1'='1'`，所有人的所有訂單都被取消。查詢版本則會把整張 orders 表（含個資）倒給模型。

### P0-3. `globals()[name](**args)` 讓模型呼叫模組裡任何全域名稱

要執行哪個函式，完全由模型輸出的字串決定，沒有白名單。

**出事情境。** 今天模型就能呼叫 `run`（遞迴，燒額度）或 `OpenAI`（用模型給的 `base_url` 建立 client）。明天有人在同一個檔案加了 `refund()` 或 import 一個危險函式，模型立刻就能呼叫，沒有人審查過這個暴露面。模型幻想出不存在的工具名稱時，`KeyError` 讓整個請求變成 500。

### P0-4. API 金鑰寫死在原始碼

**出事情境。** 程式碼進了 git，所有能讀 repo、CI log 或容器映像的人都拿得到金鑰。拿到的人可以用這把 Agent 專屬金鑰燒光每月額度，帳也會算在這個 Agent 頭上。要換金鑰就得改程式、重新部署。

### P1-5. 少了 assistant 訊息，任何工具呼叫之後的下一輪必定失敗

依照 OpenAI Chat Completions 的規則，`role: "tool"` 的訊息前面必須有一則帶 `tool_calls` 的 assistant 訊息，否則 API 回 400。原程式只 append 工具結果，沒有 append 模型那則 assistant 訊息。

**出事情境。** 只要模型呼叫工具，第二次請求就 400，這個 Agent 沒辦法完成任何一個需要工具的對話。更糟的是取消已經在第一輪執行了。使用者看到錯誤再試一次，同一張訂單又被取消一次。

### P1-6. 取消沒有業務規則、沒有冪等、沒有確認

**出事情境。** 已出貨的訂單也會被改成 `cancelled`，倉庫照樣出貨，帳務對不起來。重試，或模型在同一輪送出兩個相同的 tool call（parallel tool calls），就會重複執行。取消是不可逆的動作，現在只要模型「覺得」使用者想取消就會執行。

### P1-7. `while True` 沒有上限

**出事情境。** 模型反覆呼叫工具（例如一直查不到就一直查），請求永遠不結束。HTTP worker 被佔住，token 持續消耗。這把金鑰有每月額度，一個失控的對話可以吃掉所有使用者的額度。

### P1-8. 沒有錯誤處理，也沒有逾時

**出事情境。** 模型偶爾會輸出不合法的 JSON，`json.loads` 丟例外。模型少給或多給參數，`**args` 丟 `TypeError`。DB 斷線、Gateway 回 429 或 5xx，整個請求直接 500，使用者只看到錯誤。OpenAI client 沒設 timeout，SDK 預設會等很久，容器的連線會被拖住。

### P1-9. 個資整包送進雲端模型

`SELECT *` 加上 `str(result)`，會把電話、地址、付款資訊全部送給模型。

**出事情境。** 違反公司「送往雲端模型的內容不得含客人個資」的規定（題 3 的情境）。也浪費 token。`str()` 出來的資料列格式，模型也不一定讀得懂。

### P1-10. 模型名稱寫死 `gpt-4o`

Gateway 上的模型名稱是別名，例如 `chat-default`、`chat-cheap`。

**出事情境。** Gateway 沒有設定 `gpt-4o` 這個名稱，每個請求都失敗。就算有，也繞過了平台的路由、成本與降級政策。要換模型就得改程式。

### P1-11. 沒處理 `finish_reason` 與空內容

**出事情境。** 回覆被截斷（`length`）或被內容過濾（`content_filter`）時，`msg.content` 可能是 `None`。HTTP 層會回傳空值，或在序列化時出錯。

### P2-12. 全域狀態，無法測試

`db` 沒有定義，程式第一次呼叫工具就 `NameError`。client 在 import 時建立，測試無法替換成假的。沒有資料庫連線的生命週期管理。

### P2-13. 工具 schema 太薄

沒有 `required`，沒有 `additionalProperties: false`，沒有格式限制，說明只有四個字。

**出事情境。** 模型給出 `{}` 就 `TypeError`。說明不夠，模型不知道什麼時候該呼叫、能不能取消已出貨的訂單。schema 與函式簽章手寫兩份，改了一邊忘了另一邊。

### P2-14. 沒有日誌、審計、追蹤

**出事情境。** 客訴「我的訂單被取消了」時，回答不了「誰、在什麼時候、透過哪個對話取消的」。這部分由題 2 的工具伺服器處理。

### P2-15. 只有單輪對話

沒有對話歷史。「確定要取消 A1001 嗎？」「要」這種兩步流程做不到，模型只能在一輪內自己決定。

### P2-16. System prompt 太弱

沒有限定範圍，沒有要求取消前確認，沒有說錯誤時要怎麼回。補強 prompt 有幫助，但 prompt 只能降低機率，不能當安全邊界。安全要靠 P0-1 到 P0-3 的程式碼修正。

## 我挑的三個問題與修法

| 修的問題 | 為什麼挑它 | 修法 |
| --- | --- | --- |
| P0-1 身分與授權 | 一句話就能動到別人的訂單，影響最大 | `run()` 多一個 `user_id` 參數，由 HTTP 層從驗證過的 SSO 身分帶進來，模型碰不到。查詢與取消的 SQL 一律帶 `owner_id = ?`。別人的訂單與不存在的訂單回一樣的 `NOT_FOUND`，避免被逐一試出哪些編號存在 |
| P0-2 SQL injection | 一句話能取消整張表，不可逆 | 全部改成參數化查詢。另外用 schema 的 `pattern` 限制訂單編號格式，這是第二道防線，不是主要防線 |
| P0-3 任意函式呼叫 | 模型能呼叫的範圍沒有邊界，而且會隨著檔案內容默默變大 | 白名單註冊表 `build_tools()`，未知名稱回 `UNKNOWN_TOOL`。參數用 pydantic 驗證，壞 JSON 與錯誤參數回 `INVALID_ARGUMENTS` 給模型，不讓請求崩潰。工具的 schema 從同一個 pydantic model 產生，不再手寫兩份 |

改寫時順手修了幾個問題，不算在三個裡面。前三項和 P0-3 在同一個迴圈裡，改寫時一起處理比較自然。

- 補上 assistant 訊息（P1-5）。
- 步數上限 `max_steps`（設定檔，預設 5），超過就回固定的道歉訊息，而且最後一步不再執行工具（P1-7）。
- 工具執行的例外回給模型，不讓整個請求崩潰（P1-8）。
- 金鑰與 Gateway 網址改從環境變數讀（P0-4）。
- 模型名稱改用可設定的 Gateway 別名，預設 `chat-default`（P1-10）。
- client 設了 timeout 與重試次數（P1-8）。
- SQL 只選模型需要的欄位，電話與地址不會離開資料庫那一層（P1-9）。
- 取消用條件式 `UPDATE ... AND status IN ('pending_payment', 'paid')`，已出貨不能取消，重複取消回 `already_cancelled`（P1-6 的一部分）。

## 沒修的部分與下一步

- **取消前確認。** 應該由程式強制，而不是寫在 prompt 裡。做法是工具第一次呼叫只回傳「待確認」與摘要，由前端讓使用者按確認後才真正執行。
- **對話歷史。** 需要一個以 session 為單位的訊息存放處，加上長度上限。
- **審計記錄與更完整的業務規則。** 在題 2 的獨立工具伺服器實作。
- **個資遮罩。** 在題 3 的模組實作。
- **HTTP 層。** 這裡只示範 Agent 核心。HTTP 層要負責驗證 JWT、把 `user_id` 傳給 `run()`、把 `openai.APIError` 轉成 503。

## 測試與問題的對應

| 問題 | 測試 |
| --- | --- |
| P0-1 | `test_member_cannot_read_another_members_order`、`test_member_cannot_cancel_another_members_order` |
| P0-2 | `test_injection_payload_from_model_cancels_nothing`、`test_repository_treats_injection_payload_as_a_plain_value` |
| P0-3 | `test_model_cannot_call_functions_outside_the_registry` |
| P0-4、P1-10 | `test_settings_come_from_the_environment_not_the_source`、`test_requests_use_the_configured_gateway_alias` |
| P1-5 | `test_tool_result_follows_the_assistant_message_that_requested_it` |
| P1-6 | `test_shipped_order_is_not_cancelled`、`test_repeated_cancel_reports_already_cancelled`、`test_member_cancels_own_paid_order` |
| P1-7 | `test_loop_gives_up_after_max_steps`、`test_tool_call_on_the_last_step_is_not_run` |
| P1-8 | `test_malformed_tool_arguments_are_reported_to_the_model` |
| P1-9 | `test_own_order_reaches_model_without_phone_or_address` |

測試用假的 Gateway 取代模型。假 Gateway 回傳 OpenAI SDK 真正的 `ChatCompletion` 型別，並記下每次送出的請求，所以測試檢查的是「實際送給 Gateway 的內容」，而不是內部函式怎麼被呼叫。

為了確認測試真的抓得到問題，Claude Code 把修正一個一個改回壞掉的樣子：拿掉 `owner_id` 條件、拿掉 assistant 訊息、放寬步數上限、讓未知工具名稱也能執行、拿掉出貨狀態檢查、把查詢改回 f-string。六種改法各自讓至少一個測試失敗。

## AI 工具使用說明

- 問題清單、嚴重程度排序、修正版程式和測試，是 Claude Code 產出的。
- 我做的事：對照原始程式讀過問題清單，跑過測試。
- 我自己判斷的部分：選來修的三個（沒有身分、SQL injection、`globals()`）我同意。這三個都是使用者打一句話，就能查到或取消別人的訂單。金鑰寫死也很嚴重，但要先拿到程式碼才會出事，所以我排在後面。
