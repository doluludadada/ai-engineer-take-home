from typing import override

from a_domain.ports.system.personal_data_filter import IPersonalDataFilter
from pii_guard import Vault, mask


class PiiGuardFilter(IPersonalDataFilter):
    """
    Removes personal data with the question 3 module, pii_guard. Each call masks into a new vault and drops it, so
    nothing can turn a placeholder such as [PHONE_1] back into the number.
    """

    @override
    def remove(self, text: str) -> str:
        return mask(text, Vault())
