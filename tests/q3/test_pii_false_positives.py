"""Business numbers that look like PII must reach the model unchanged."""

from pii_guard import Vault, mask


def assert_untouched(text):
    assert mask(text, Vault()) == text


def test_dated_order_number_is_not_masked():
    # 19 digits, passes Luhn, and holds 0912345678 in the middle.
    assert_untouched("您的訂單 2026110609123456780 已出貨")


def test_prefixed_order_number_is_not_masked():
    assert_untouched("訂單 ORD-20261106-0912345678 已取消")


def test_sku_is_not_masked():
    assert_untouched("商品 SKU-A123456789 缺貨中")


def test_amount_with_thousands_separators_is_not_masked():
    assert_untouched("本月總計 NT$1,234,567,890，請確認")


def test_card_shaped_amount_is_not_masked():
    assert_untouched("應付金額：4111111111111111 元")


def test_sixteen_digits_failing_luhn_is_not_masked():
    assert_untouched("卡號 4111 1111 1111 1112 刷卡失敗")


def test_national_id_shape_with_bad_checksum_is_not_masked():
    assert_untouched("證號 A123456788 格式錯誤")


def test_order_id_label_before_phone_shaped_number_is_not_masked():
    assert_untouched("訂單編號 0912345678 已出貨")
    assert_untouched("物流單號：0912345678")


def test_datetime_is_not_masked():
    assert_untouched("下單時間 20261106091238，付款時間 2026-11-06 09:12:38")


def test_phone_inside_longer_digit_run_is_not_masked():
    assert_untouched("追蹤碼 880912345678、091234567890 與 TW0912345678")


def test_phone_label_next_to_order_word_is_still_masked():
    assert mask("訂單聯絡電話 0912345678", Vault()) == "訂單聯絡電話 [PHONE_1]"


def test_label_naming_both_order_and_phone_is_masked():
    assert mask("手機訂單編號 0912345678", Vault()) == "手機訂單編號 [PHONE_1]"


def test_order_word_earlier_in_the_clause_does_not_hide_a_phone():
    assert mask("單號查好了請打給我 0912345678", Vault()) == "單號查好了請打給我 [PHONE_1]"


def test_formatted_phone_after_order_label_is_masked():
    assert mask("訂單編號 0912-345-678", Vault()) == "訂單編號 [PHONE_1]"
