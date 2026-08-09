"""EQS Group / DGAP 德国监管披露连接器（桩实现，market=de）。

DE-2 阶段只留桩：不对标 SEC / AMF OAM 做真实采集，``collect()`` 恒定
返回空列表、不发任何网络请求。URL 模板仅是占位，供后续 DE 任务填充
真实端点与解析逻辑。
"""

from __future__ import annotations

import logging
from typing import List, Mapping, Tuple

from ...models import CollectionRequest, InformationItem

LOGGER = logging.getLogger(__name__)


class EqsDgapConnector:
    """EQS/DGAP 德国披露源桩实现。"""

    name = "eqs_dgap"
    provider = "EQS Group / DGAP"
    status = "stub"

    # 占位 URL 模板：实现 EQS/DGAP 采集时按公司 ISIN / 公告 ID 替换占位符。
    URL_TEMPLATES: Mapping[str, str] = {
        "search": "https://www.eqs-news.com/news/search?isin={isin}",
        "detail": "https://www.eqs-news.com/news/{external_id}",
    }

    def __init__(self) -> None:
        self._last_errors: Tuple[Tuple[str, str], ...] = ()

    @property
    def last_errors(self) -> Tuple[Tuple[str, str], ...]:
        """返回上次采集的失败记录（桩实现恒为空）。"""
        return self._last_errors

    def collect(self, request: CollectionRequest) -> List[InformationItem]:
        """桩：不联网，恒返回空列表。"""
        return []
