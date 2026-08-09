"""德国市场社区数据连接器（桩实现，market=de）。

DE-4 阶段只留桩：对标 FR 社区源的诚实声明方式，先注册 Source 并标注
待后续接入，``collect()`` 恒定返回空列表、不发任何网络请求。URL 模板
仅是占位，供后续 DE 任务填充真实端点与解析逻辑。
"""

from __future__ import annotations

import logging
from typing import List, Mapping, Tuple

from ...models import CollectionRequest, InformationItem

LOGGER = logging.getLogger(__name__)


class DeCommunityConnector:
    """DE 社区数据源桩实现（已注册，待后续接入）。"""

    name = "de_community"
    provider = "DE Community"
    status = "stub"

    # 占位 URL 模板：接入社区数据时按公司 / 帖子 ID 替换占位符。
    URL_TEMPLATES: Mapping[str, str] = {
        "search": "https://community.example.test/search?ticker={ticker}",
        "detail": "https://community.example.test/posts/{external_id}",
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