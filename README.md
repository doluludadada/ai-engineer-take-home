# AI 開發工程師筆試作答

## 繳交內容

| 題目 | 內容 | 位置 |
| --- | --- | --- |
| 題 1 程式碼審查 | 問題清單（依嚴重程度排序）、三個最重要問題的修正程式碼、測試 | [`q1_review/REVIEW.md`](q1_review/REVIEW.md)、[`q1_review/order_agent.py`](q1_review/order_agent.py)、[`tests/q1/`](tests/q1/) |
| 題 2 訂單工具伺服器 | MCP 工具伺服器（JWT 身分與授權、不會重複執行的取消、審計與遮罩），用我平常的 Clean Architecture 分層 | [`order_tools/README.md`](order_tools/README.md)、[`order_tools/`](order_tools/)、[`tests/q2/`](tests/q2/) |
| 題 3 個資遮罩與還原 | 送出前遮罩、回來後還原、降低誤判、串流還原、README、測試 | [`pii_guard/README.md`](pii_guard/README.md)、[`pii_guard/`](pii_guard/)、[`tests/q3/`](tests/q3/) |
| 題 4 評估 | 解讀、樣本夠不夠、捏造的防線、LLM 評審的風險 | [`docs/q4_evaluation.md`](docs/q4_evaluation.md) |
| 題 5 技術提案 | 規章問答助理的一頁提案、過去專案 | [`docs/q5_proposal.md`](docs/q5_proposal.md) |

## 如何執行

需要 [uv](https://docs.astral.sh/uv/)。Python 用 3.14，`uv sync` 會自己裝。不需要任何模型 API 金鑰，模型和後端都用假的回應或本機 SQLite 代替。

```bash
uv sync
uv run pytest            # 全部測試，190 個
uv run pytest tests/q2   # 只跑某一題
```

有裝 [just](https://github.com/casey/just) 的話，`just` 會列出所有指令，例如 `just test`、`just demo`（題 2 的示範伺服器）、`just check`（ruff 和 pyright）。

## AI 工具使用說明

這份作業我主要是用 Claude Code 做的，搭配一套 workflow 外掛（pstack），它會要求 AI 先列決策、寫測試、自己驗證過再交。

- 題 1 到題 3：程式碼、測試和 README 是 Claude Code 產出的。題 2 的架構是我要求照我自己專案的規則重排的。
- 題 4、題 5：Claude Code 依我的經歷起草，我再改。
- 題 5 的過去專案：是我自己的經驗。

每一題最後都有寫 AI 做了什麼、我自己做了什麼或同意哪些決定；有不熟的部分也寫在那裡。
