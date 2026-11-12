import copy
import json
import re
import time

import pytest

from pii_guard import DEFAULT_PROTECTED, Vault, mask, mask_messages, unmask


@pytest.mark.parametrize(
    "phone",
    [
        "0912345678",
        "0912-345-678",
        "0912 345 678",
        "0912-345678",
        "+886 912 345 678",
        "+886-912-345-678",
        "+886912345678",
        "886912345678",
        "０９１２３４５６７８",
    ],
)
def test_mobile_phone_formats_are_masked(phone):
    assert mask(f"我的手機是{phone}，謝謝", Vault()) == "我的手機是[PHONE_1]，謝謝"


@pytest.mark.parametrize("email", ["amy@example.com", "amy.lin+shop@mail.example.com.tw"])
def test_email_is_masked(email):
    assert mask(f"請寄到 {email} 。", Vault()) == "請寄到 [EMAIL_1] 。"


@pytest.mark.parametrize(
    "national_id",
    [
        "A123456789",
        "a123456789",
        "F131104093",
        "A800000005",  # new-format resident certificate, second digit 8
    ],
)
def test_national_id_with_valid_checksum_is_masked(national_id):
    assert mask(f"身分證字號{national_id}", Vault()) == "身分證字號[NATIONAL_ID_1]"


@pytest.mark.parametrize(
    "card",
    [
        "4111 1111 1111 1111",
        "4111-1111-1111-1111",
        "4111111111111111",
        "3782 822463 10005",
        "6212 3456 7890 1234",  # UnionPay, fails Luhn
    ],
)
def test_card_number_is_masked(card):
    assert mask(f"卡號：{card}，有效期限 12/28", Vault()) == "卡號：[CREDIT_CARD_1]，有效期限 12/28"


MIXED = "我是王小明，手機 0912-345-678，email amy@example.com，身分證 A123456789，刷卡 4111 1111 1111 1111，訂單 ORD-20261106-0001。"
MIXED_PII = ["0912-345-678", "amy@example.com", "A123456789", "4111 1111 1111 1111"]


def test_masked_text_contains_no_original_pii():
    masked = mask(MIXED, Vault())
    for value in MIXED_PII:
        assert value not in masked
    assert "ORD-20261106-0001" in masked


def test_round_trip_restores_the_original_text():
    vault = Vault()
    assert unmask(mask(MIXED, vault), vault) == MIXED


def test_same_value_keeps_its_placeholder_and_new_values_get_new_numbers():
    vault = Vault()
    first = mask("手機 0912345678", vault)
    second = mask("另一支 0987654321，原本那支 0912345678", vault)
    assert first == "手機 [PHONE_1]"
    assert second == "另一支 [PHONE_2]，原本那支 [PHONE_1]"


def test_unknown_placeholder_in_reply_is_left_alone():
    vault = Vault()
    mask("手機 0912345678", vault)
    assert unmask("撥 [PHONE_1] 或 [PHONE_9]，寄 [EMAIL_1]", vault) == "撥 0912345678 或 [PHONE_9]，寄 [EMAIL_1]"


def test_literal_placeholder_typed_by_user_survives_round_trip():
    vault = Vault()
    text = "範本裡的 [PHONE_1] 要換成 0912345678"
    masked = mask(text, vault)
    assert masked == "範本裡的 [PHONE_1] 要換成 [PHONE_2]"
    assert unmask(masked, vault) == text


def test_vault_repr_does_not_reveal_values():
    vault = Vault()
    mask("手機 0912345678，email amy@example.com", vault)
    assert "0912345678" not in repr(vault)
    assert "amy@example.com" not in repr(vault)


def test_mask_messages_handles_string_and_list_content_without_mutating_input():
    messages = [
        {"role": "system", "content": "你是客服助理。"},
        {"role": "user", "content": "我的手機 0912345678"},
        {
            "role": "user",
            "content": [
                {"type": "text", "text": "email 是 amy@example.com"},
                {"type": "image_url", "image_url": {"url": "https://example.com/receipt.png"}},
            ],
        },
    ]
    before = copy.deepcopy(messages)

    masked = mask_messages(messages, Vault())

    assert messages == before
    assert masked == [
        {"role": "system", "content": "你是客服助理。"},
        {"role": "user", "content": "我的手機 [PHONE_1]"},
        {
            "role": "user",
            "content": [
                {"type": "text", "text": "email 是 [EMAIL_1]"},
                {"type": "image_url", "image_url": {"url": "https://example.com/receipt.png"}},
            ],
        },
    ]


def test_mask_messages_masks_tool_call_arguments_and_tool_results_in_history():
    messages = [
        {
            "role": "assistant",
            "content": None,
            "tool_calls": [
                {"id": "call_1", "type": "function", "function": {"name": "find_orders", "arguments": '{"phone": "0912345678"}'}}
            ],
        },
        {"role": "tool", "tool_call_id": "call_1", "content": '{"buyer_email": "amy@example.com"}'},
    ]

    masked = mask_messages(messages, Vault())

    assert masked[0]["content"] is None
    assert masked[0]["tool_calls"][0]["function"]["arguments"] == '{"phone": "[PHONE_1]"}'
    assert masked[1]["content"] == '{"buyer_email": "[EMAIL_1]"}'


def test_literal_placeholder_in_a_later_message_is_not_reused_for_an_earlier_value():
    vault = Vault()
    messages = [{"role": "user", "content": "我的手機 0912345678"}, {"role": "user", "content": "回覆時請保留 [PHONE_1] 這個字樣"}]

    masked = mask_messages(messages, vault)

    assert masked[0]["content"] == "我的手機 [PHONE_2]"
    assert unmask(masked[1]["content"], vault) == "回覆時請保留 [PHONE_1] 這個字樣"


def test_restored_tool_arguments_stay_valid_json():
    vault = Vault()
    mask("我的手機 0912-345-678，email amy.lin+shop@example.com", vault)
    arguments = '{"phone": "[PHONE_1]", "email": "[EMAIL_1]"}'
    assert json.loads(unmask(arguments, vault)) == {"phone": "0912-345-678", "email": "amy.lin+shop@example.com"}


def test_caller_can_add_a_protected_pattern():
    invoice = "INV-4111111111111111"
    protected = (*DEFAULT_PROTECTED, re.compile(r"INV-\d+"))
    assert mask(f"發票 {invoice}", Vault()) == "發票 INV-[CREDIT_CARD_1]"
    assert mask(f"發票 {invoice}", Vault(), protected) == f"發票 {invoice}"


def test_email_shaped_input_without_domain_stays_linear():
    # A pattern that retries from every letter takes seconds here. A linear one takes milliseconds.
    text = "a" * 50_000 + "@" + "b" * 50_000
    started = time.perf_counter()
    assert mask(text, Vault()) == text
    assert time.perf_counter() - started < 1.0


def test_pasted_customer_list_stays_fast():
    rows = "".join(f"客戶{i} 手機 09{i:08d}\n" for i in range(20_000))
    started = time.perf_counter()
    masked = mask(rows, Vault())
    elapsed = time.perf_counter() - started
    assert masked.splitlines()[-1] == "客戶19999 手機 [PHONE_20000]"
    assert elapsed < 1.0


@pytest.mark.parametrize(
    ("text", "masked"),
    [
        ("卡號 4111 1111 1111 1111 元大銀行的卡", "卡號 [CREDIT_CARD_1] 元大銀行的卡"),
        ("我的手機 0912345678 元旦後請再打給我", "我的手機 [PHONE_1] 元旦後請再打給我"),
    ],
)
def test_number_before_a_word_that_only_starts_like_an_amount_marker_is_masked(text, masked):
    assert mask(text, Vault()) == masked


def test_tool_call_of_an_unknown_shape_blocks_the_request():
    messages = [{"role": "assistant", "tool_calls": [{"id": "call_1", "type": "custom", "custom": {"input": "0912345678"}}]}]

    with pytest.raises(KeyError):
        mask_messages(messages, Vault())


@pytest.mark.parametrize(
    ("text", "masked"),
    [
        ("卡號 4111 1111 1111 1111 123", "卡號 [CREDIT_CARD_1] 123"),
        ("卡號 4111-1111-1111-1111-123", "卡號 [CREDIT_CARD_1]-123"),
        ("3782 8224 6310 005", "[CREDIT_CARD_1]"),
        ("4111\u00a01111\u00a01111\u00a01111", "[CREDIT_CARD_1]"),
    ],
    ids=["security-code-after", "security-code-after-hyphens", "fifteen-digits-in-fours", "non-breaking-spaces"],
)
def test_grouped_card_numbers_are_masked(text, masked):
    assert mask(text, Vault()) == masked


@pytest.mark.parametrize(
    ("text", "masked"),
    [
        ("手機0912345678LINE同號", "手機[PHONE_1]LINE同號"),
        ("0912\u2011345\u2011678", "[PHONE_1]"),
        ("門號與金額：0912345678 300元", "門號與金額：[PHONE_1] 300元"),
        ("amy@gmail.com-0912345678", "[EMAIL_1]-[PHONE_1]"),
        ("ord-team@example.com", "[EMAIL_1]"),
    ],
    ids=["glued-to-a-word", "typographic-hyphens", "beside-an-amount", "email-then-phone", "email-that-looks-like-an-order"],
)
def test_phone_and_email_in_awkward_places_are_masked(text, masked):
    assert mask(text, Vault()) == masked


def test_arguments_of_an_old_style_function_call_are_masked():
    messages = [{"role": "assistant", "content": None, "function_call": {"name": "find", "arguments": '{"phone": "0912345678"}'}}]

    assert mask_messages(messages, Vault())[0]["function_call"]["arguments"] == '{"phone": "[PHONE_1]"}'
