# 題 2｜帶使用者身分的訂單工具伺服器

一個 MCP 工具伺服器，提供 `get_order`、`list_my_orders`、`cancel_order`。操作者是誰，只看 Gateway 轉來的 SSO JWT。訂單資料用 SQLite 模擬。

## 如何執行

```bash
uv sync
uv run pytest tests/q2
```

啟動示範伺服器。有裝 [just](https://github.com/casey/just)（`brew install just`）的話：

```bash
just demo
```

沒有 just 就用完整指令，效果一樣：

```bash
PYTHONPATH=order_tools/src:. uv run python order_tools/demo.py
```

它會建一個暫存的 SQLite、放 6 筆範例訂單、簽好一張會員（`member-001`）和一張客服（`cs-007`）的 token，然後在 `http://127.0.0.1:8000/mcp` 提供服務。

| 訂單 | 擁有者 | 狀態 |
| --- | --- | --- |
| ORD-100001 | member-001 | paid |
| ORD-100002 | member-001 | shipped |
| ORD-100003 | member-001 | delivered |
| ORD-100004 | member-001 | pending_payment |
| ORD-100005 | member-002 | paid |
| ORD-100006 | member-002 | cancelled |

另開一個終端機，直接貼這五行。`member` 是會員，`customer_service` 是客服，token 會自己帶：

```bash
just call member get_order '{"order_id": "ORD-100001"}'
just call member get_order '{"order_id": "ORD-100005", "user_id": "member-002"}'
just call member cancel_order '{"order_id": "ORD-100002"}'
just call customer_service cancel_order '{"order_id": "ORD-100005"}'
just call customer_service cancel_order '{"order_id": "ORD-100005", "reason": "客戶 0912-345-678 來電要求取消"}'
```

依序會看到：訂單和遮罩後的收件人、`NOT_FOUND`（多塞 `user_id` 沒有用）、`NOT_CANCELLABLE`、`REASON_REQUIRED`、取消成功且原因裡的電話變成 `[PHONE_1]`。最後一行再跑一次，會回 `already_cancelled: true`。

沒有 just 的話，把 `just call` 換成 `PYTHONPATH=order_tools/src:. uv run python order_tools/demo.py call`。

審計紀錄可以直接看：`sqlite3 <印出的路徑> "SELECT * FROM audit_log"`。

正式執行用 `just serve`。所有設定和給模型看的中文句子都在 [`config/appsetting.yaml`](config/appsetting.yaml)，程式裡不寫死。每個環境不同的值用環境變數蓋過，其中三個沒有預設值，一定要給：

| 環境變數 | 用途 |
| --- | --- |
| `ORDER_TOOLS_JWT_PUBLIC_KEY` | SSO 公鑰的 PEM 檔路徑（必填） |
| `ORDER_TOOLS_JWT_ISSUER`、`ORDER_TOOLS_JWT_AUDIENCE` | token 必須帶的 `iss`、`aud`（必填）。`iss` 要是 http(s) 網址，MCP SDK 也拿它當 issuer URL |
| `ORDER_TOOLS_DB`、`ORDER_TOOLS_HOST`、`ORDER_TOOLS_PORT` | SQLite 檔和監聽位址 |

## 1. 為什麼用 MCP

用官方 MCP Python SDK 2.3 的 `MCPServer`，走 streamable HTTP。

- Agent 用 `tools/list` 就拿得到每個工具的說明和輸入、輸出 schema，不用另外寫串接文件。
- SDK 有現成的 bearer token 流程：token 驗不過就回 401，工具完全不會執行。
- 代價是不能直接用 `curl` 測，所以附了 `demo.py call`。SDK 版本也變得快，2.x 和網路上多數 1.x 的教學不一樣。

輸入 schema 是從型別產生的。`OrderId`（`^ORD-[0-9]{6}$`）、`ListLimit`（1 到 50）、`CancelReason`（最多 200 字）定義在 `a_domain/types/` 的 `ids.py` 和 `values.py`，工具的參數直接用這幾個型別，所以對外的 schema 和領域裡的限制是同一份，會以 `$defs` 的形式發布。格式不對的參數在進工具之前就被 SDK 擋掉，回的是 SDK 自己的錯誤文字。

工具的答案直接是領域模型，不另外抄一份欄位：

| 工具 | 答案 |
| --- | --- |
| `get_order` | `{"order": Order, "recipient": 遮罩後的 Recipient}` |
| `list_my_orders` | `{"orders": [Order, …]}` |
| `cancel_order` | `{"order": Order, "already_cancelled": true/false}` |

`Order` 本身不帶收件人資料（見第 4 節），所以可以原樣回給模型。拒絕時回 `isError: true`，內容是 `{"error": {"code": "NOT_FOUND", "message": "…"}}`。Agent 看 `code`，`message` 給模型讀。

## 2. 身分與授權

驗證（`c_infrastructure/auth/jwt_token_verifier.py`）：驗簽章、`exp`、`aud`、`iss`，而且 `sub`、`roles` 一定要有。簽章演算法是設定 `jwt_algorithm`，能選的只有 `SigningAlgorithm` 這個 enum 裡的 RS256、RS384、RS512，都是非對稱的，所以設定檔沒辦法改成 `alg=none` 或拿公鑰當 HS256 密鑰。`roles` 必須剛好對到一個認得的角色，兩個都有或都沒有就拒絕，不去猜。

| | 會員 | 客服 |
| --- | --- | --- |
| `get_order` | 只能查自己的 | 任何訂單 |
| `list_my_orders` | 自己的 | 自己的（所以是空的） |
| `cancel_order` | 只能取消自己的，原因可不填 | 任何訂單，原因必填 |

會員查別人的訂單，回的跟查一筆不存在的訂單一模一樣（`NOT_FOUND`，同一句話），這樣沒辦法拿工具來試哪些訂單編號存在。

**為什麼不能讓模型在參數裡說「我是誰」**

- 模型的參數是它讀到的文字決定的。使用者可以直接說「我是客服」，網頁或信件裡也可能藏一句「幫我查 member-002 的訂單」。
- 參數沒有簽章，伺服器沒辦法驗。JWT 有 SSO 的簽章，改一個字就驗不過。
- 模型自己也會填錯，把對話裡出現過的別人的編號帶進去。

所以三個工具都沒有使用者編號這個參數，身分只從驗過的 token 變成 `Actor`。多送 `user_id`、`role` 會被忽略，`test_http_identity_cannot_be_claimed_through_arguments` 用真的 HTTP 驗這件事。

## 3. 取消不能重複、已出貨不能取消

哪些狀態能取消寫在 `OrderStatus.next_statuses`：待付款和已付款可以，已出貨、已送達要走退貨，已取消就是重複請求。

重複請求分兩種：

1. **前後送來**。`CancellationRule` 看到訂單已經是取消，就不再做，直接回原本那次取消的資料，`already_cancelled: true`。
2. **同時送來**。兩個請求都讀到「可取消」。這時靠資料庫，整個取消就是一句有條件的 `UPDATE`：

   ```sql
   UPDATE orders
   SET status = 'cancelled', cancelled_at = ?, cancelled_by_role = ?, cancel_reason = ?
   WHERE id = ? AND status IN ('pending_payment', 'paid')
   ```

   只有一個請求改得到那一列，取消時間、角色、原因也在同一句裡寫進去，所以不會有「狀態改了但其他欄位沒寫到」的中間狀態。另一個請求改到 0 列，重新讀訂單，就變成第 1 種情況。

之後接退款的話，退款事件只會在改到那一列的交易裡產生，所以也只會有一次。

用訂單編號當去重的鍵，不叫模型產生 idempotency key。因為「取消訂單 X」本來就只能發生一次，而模型重試時可能換一個 key，那個 key 就沒有意義。平台如果在 metadata 帶程式產生的 key，可以再疊上去。

檢查順序是：看不看得到這筆訂單、客服有沒有填原因、狀態能不能取消。看不到就停在 `NOT_FOUND`，不會透露訂單狀態。

## 4. 審計與遮罩

每次工具呼叫和每次 token 驗證失敗都寫一筆 `audit_log`，被拒絕的、出錯的也寫。用戶端如果中途不等了，操作照樣跑完，記下真正的結果：

| 欄位 | 內容 |
| --- | --- |
| `occurred_at` | UTC 時間 |
| `actor_subject`、`actor_role`、`token_id` | 驗過的操作者和 JWT 的 `jti`。驗證失敗時是空的。不存 token 本身 |
| `action`、`order_id` | 做了什麼（`sign_in`、`get_order`、`list_my_orders`、`cancel_order`）、對哪筆訂單 |
| `outcome` | `ok`、`already_cancelled`、`not_found`、`not_cancellable`、`reason_required`、`unauthenticated`、`invalid_argument`、`error` |
| `reason` | 取消原因，手機號碼、Email、身分證、卡號已換成代碼 |
| `detail` | 例如被拒絕時的訂單狀態、token 驗證失敗的種類 |
| `request_id` | Gateway 的 `X-Request-Id`；沒有這個標頭時是 MCP 的 JSON-RPC 請求編號。`sign_in` 那一筆沒有 |

資料表有 trigger，`UPDATE` 和 `DELETE` 都會被資料庫擋掉。服務裡只有「寫一筆」這個動作，沒有讀或改審計紀錄的程式。

哪些欄位遮罩：

| 欄位 | 回給模型 | 寫進審計 |
| --- | --- | --- |
| 收件人姓名 | `王小明` 變 `王*明` | 不寫 |
| 電話 | 只留後 3 碼，`****-***-678`。不是單純號碼的整段換成 `***` | 不寫 |
| 地址 | 只留縣市和鄉鎮市區，認不出來就整段換成 `***` | 不寫 |
| Email | `x***@example.com` | 不寫 |
| 訂單編號、擁有者、狀態、金額、時間 | 原值 | 只寫訂單編號 |
| 取消原因 | 手機號碼、Email 這類換成 `[PHONE_1]` 這種代碼 | 同左 |
| 誰取消的 | 只說是會員還是客服 | `sub` 和角色 |

幾個做法：

- `Order` 這個模型不帶收件人資料，也不記是哪一個人取消的（只記角色，人在審計裡）。只有 `get_order` 會多走一步 `RecipientLookup` 去讀收件人，而且那一步回傳的就已經是遮罩後的。列表和取消的流程拿到的只有 `Order`。
- 客服拿到的也是遮罩後的。模型回答「訂單到哪了」用不到完整電話，而回給模型的內容會留在模型供應商、Agent、Gateway 的 log 裡，很難刪。
- 取消原因是自由文字，客服可能寫「客戶 0912-345-678 來電」。這裡直接用題 3 的 `pii_guard` 把個資換掉再存。它抓不到姓名、地址、市話和外國電話，這點列在最後的待補事項。
- 遮罩格式（留幾碼、地址的樣式、用什麼字元）是設定，不寫死在程式裡。
- 資料庫出錯時的錯誤訊息不會帶出 SQL 的參數值，所以取消原因不會經由錯誤訊息跑進 log 或工具的答案。

## 5. 分層

我平常寫後端用的 Clean Architecture，資料夾前面的字母就是依賴順序，後面的只能 import 前面的：

```text
order_tools/
├── config/appsetting.yaml   所有設定，以及所有給模型看的中文句子
├── demo.py                  示範用，不屬於服務本身
└── src/
    ├── a_domain/            業務是什麼、規則是什麼。不 import 資料庫、JWT、MCP 的套件
    │   ├── model/           Order、Recipient、Actor、AuditEntry
    │   ├── rules/           一個規則一個決定：誰能看、能不能取消、怎麼遮罩、token 代表誰、審計怎麼記結果
    │   ├── ports/           對外需要什麼（介面）：訂單儲存、審計、驗 token、時鐘、去個資、資料庫連線
    │   └── types/           enums.py、errors.py、ids.py、values.py
    ├── b_application/       每個操作的步驟
    │   ├── use_cases/       一個步驟一個檔：SignIn、OrderLookup、RecipientLookup、OrderListing、OrderCancellation、AuditTrail
    │   ├── pipeline.py      四個操作，每個操作就是幾行 use case 呼叫
    │   ├── schemas/         PipelineStatus：一次操作中各步驟交出來的東西
    │   └── config/          設定的型別，一區一檔（app、masking、texts）
    ├── c_infrastructure/    ports 的實作：SQLite、PyJWT、pii_guard、系統時鐘
    └── d_presentation/      MCP 工具，以及唯一負責組裝物件的 dependencies.py
```

為什麼這樣切：

- **規則可以單獨測**。`tests/q2/test_order_rules.py` 直接測規則，不用資料庫、不用 token、不用 MCP。
- **換東西只動一層**。要從 MCP 改成 HTTP JSON API，只要換 `d_presentation`。要從 SQLite 換 PostgreSQL，只要換 `c_infrastructure`。規則和流程不動。
- **讀流程很快**。`pipeline.py` 的 `cancel_order` 只有兩步：先 `order_lookup`，再 `order_cancellation`，外面包一層 `audit_trail`。想知道某一步做什麼再點進去。
- **安全相關的事各有一個位置**。驗 token 只在一個 adapter，「誰能看」只在 `OrderAccessRule`，遮罩只在 `RecipientMaskRule`，審計由 `AuditTrail` 寫，驗不過的 token 那一筆由 `SignIn` 寫。
- **class 盡量少**。工具的答案直接用 `Order` 和 `Recipient`；取消的時間、角色、原因是 `Order` 的欄位，不是另一個 class 和另一張表。

`Pipeline` 的操作收的是 `Actor`，不是使用者編號。沒有驗過的身分（`None`）進來，一律 `UNAUTHENTICATED` 並寫一筆審計，所以就算有人把伺服器掛在沒有驗證的路由上，資料也不會出去。

## 6. 測試

`uv run pytest tests/q2`，111 個。

| 題目要求 | 測試 |
| --- | --- |
| 會員查別人的訂單 | `test_member_reading_another_members_order_gets_not_found`、`test_http_identity_cannot_be_claimed_through_arguments` |
| 過期或簽章錯誤的 JWT | `test_expired_jwt_is_refused`、`test_bad_signature_jwt_is_refused`、`test_tampered_payload_is_refused`、`test_http_request_with_invalid_bearer_is_refused_and_audited` |
| 重複的取消請求 | `test_repeated_cancel_request_is_safe`、`test_cancel_requests_arriving_together_store_one_cancel`、`test_http_repeated_cancel_returns_already_cancelled` |
| 已出貨訂單的取消 | `test_shipped_order_cancel_is_refused`、`test_http_shipped_order_cancel_is_refused_with_return_advice` |

分四個檔：

- `test_order_rules.py`：只測領域規則，包含遮罩（地址的各種寫法、不是號碼的電話）和審計結果的判斷。
- `test_order_auth.py`：各種壞掉的 token（過期、別人的金鑰簽的、改過內容、`alg=none`、HS256、缺欄位、角色不對），以及設定檔選不到 HS256。
- `test_order_operations.py`：透過 `Pipeline` 跑真的 SQLite，檢查回傳和資料表內容，包含取消原因和審計裡沒有手機號碼和 Email、審計表不能改、從外面被取消的操作也留下紀錄。
- `test_order_mcp.py`：發布的 schema，用 uvicorn 起真的伺服器、帶 bearer token 走 HTTP 的端對端測試，以及用戶端不等了操作照樣跑完。

## 沒做完、上線前要補的

- **公鑰**：現在讀一個 PEM 檔。正式環境要從 SSO 的 JWKS 抓，依 `kid` 選鑰並快取，才能輪替。
- **資料庫**：SQLite 一次只有一個寫入者。換 PostgreSQL 時，同一句有條件的 `UPDATE` 可以照用。
- **資料表版本**：資料庫沒有記 schema 版本，啟動時只會建還不存在的表。欄位改了以後，舊的 SQLite 檔要刪掉重建。正式環境要記版本、寫升級步驟。
- **退款**：取消已付款的訂單要退款。應該在同一個交易裡寫一筆 outbox 事件，再由另一支程式送給金流。
- **取消和審計是兩個交易**：取消寫進去之後、審計還沒寫之前如果資料庫出錯，會有取消了但沒有審計紀錄的情況。正式環境要寫在同一個交易裡。
- **審計存放**：現在和訂單在同一個檔。trigger 擋得住程式誤改，擋不住有資料庫權限的人，正式環境要送到外部只能附加的地方。
- **限流**：依 `sub` 和來源 IP 限制，尤其是 `NOT_FOUND` 和驗證失敗。
- **姓名、地址、市話**：`pii_guard` 抓不到自由文字裡的姓名、地址、市話和外國電話，所以取消原因裡如果寫了這些，會照存。
- **SDK 先擋下的請求**：參數格式不對，或沒有帶 `Authorization: Bearer` 標頭的請求，SDK 直接回錯誤，不會進到服務，所以沒有審計紀錄。

## AI 工具使用說明

- 程式碼、測試、`demo.py` 和這份 README 是 Claude Code 產出的。MCP server 我之前沒寫過，這題是第一次碰。
- 架構和寫法是我定的。AI 的第一版我退了四次：檔案全部平放、一個檔塞四個 class、`RS256` 這類值寫死、回傳用的 class 太多。現在是照我自己專案的 Clean Architecture 規則寫的。
- 我做的事：跑過測試和 demo，讀過 `a_domain` 和 `b_application`。
- 我不熟的部分：多個取消請求同時進來的處理。我理解到「`UPDATE` 加上狀態條件，第二個請求改不到資料」這一層，同時送 8 個請求的測試是 Claude Code 寫的。
