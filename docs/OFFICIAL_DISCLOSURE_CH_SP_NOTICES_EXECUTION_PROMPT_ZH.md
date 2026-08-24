# 瑞士 Sponsored Foreign Shares 与 SIX 官方公告补强提示词

## 角色与范围

你是一名负责证券交易所官方证券目录和公告采集的高级工程师。只修改瑞士（CH）业务逻辑；不得修改新闻模块，不得撤销其他人的改动，不得将付费产品或未授权接口伪装成免费完整覆盖。

本批目标：

1. 将 SIX Sponsored Foreign Shares 接入现有瑞士官方证券目录和每日缓存刷新。
2. 接入 SIX Exchange Regulation 公开 Official Notices 列表及详情，按请求证券的 ISIN 精确匹配。
3. 对瑞士其他交易场所作正确的数据建模：如果只是同一证券的交易路由，不重复创建发行人；没有免费、稳定、可验证的发行人主数据合同则保留缺口。
4. 瑞士整体仍保持 `partial`，除非有证据证明发行人范围、历史证券和完整发行人披露均已对账。

## 来源裁决门

实施前必须从官方网页和真实响应确认：

- Sponsored Foreign Shares 属于 SIX 官方市场分部；公开 FQS 响应确实能以 `PortalSegment=EQ*TitleSegment=SP` 查询，返回证券类型、ISIN、Valor、交易币种和首次交易日。
- SIX/SER Official Notices 公开页面确实调用 `sheldon/official_notices/v2/find.json`，列表响应包含 `totalCount` 和零起始页码；详情使用 `details/{noticeId}.json`。
- 列表中的 `isin` 可能是单个 ISIN、多个 ISIN 拼接或 `Part I` 等非 ISIN 标签；只能提取格式合法的 ISIN，不得因非 ISIN 标签让整批失败，也不得用模糊名称匹配。
- 不调用 SIX 付费 Reference Data/Exfeed；不绕过登录、令牌、验证码、WAF 或访问限制。

任一关键合同无法在官方真实响应中验证时，停止相应实现并保留原覆盖边界。

## 实施要求

### Sponsored Foreign Shares

- 在 `SixFqsClient` 中新增必需的 SP scope，并参与分页总数、跨页重复、响应状态、源有效时间和原子缓存校验。
- 仅接受官方 `SecTypeCode=SS`、`ListingSegment=SP`、合法 ISIN/Valor/交易币种/日期的行；未知类型失败关闭。
- 保存 `trading_currency`、`first_trading_date`、`primary_listing_outside_switzerland`、官方采集 URL 和实际源有效时间。
- 同一外国证券可能有 CHF/USD 多交易行。可以将同名、同 ISIN、同证券类型的多 Valor 行解析到一个发行人身份，但必须在缓存中保留交易行歧义，不得擅自选择交易币种。
- 每日刷新只有 SA、AA、SP、ETF 四个 scope 全部成功且达到合理下限时才替换旧缓存。

### SIX Official Notices

- 实现公开 JSON 列表的全分页读取：校验 `status`、`totalCount`、每页长度、总数漂移、跨页重复和页数上限。
- 先扫描日期窗口内的完整列表，只对与请求 universe ISIN 精确相交的记录请求详情，避免把结构化产品公告误归到股票。
- 列表与详情必须交叉核对公告 ID、日期、公告类型、联系人/发行人、标题和合法 ISIN 集合。
- 保存公告 ID、官方公告编号、Valor、苏黎世时区、公告类别、官方详情 URL、实际列表/详情采集 URL、原始载荷和来源等级。
- 403、429、超时、HTML、非 JSON、结果总数不一致、分页触顶、详情身份冲突都必须失败；只有成功核对完整列表且无 ISIN 命中才是 `empty`。
- connector 必须进入 registry/settings 和日常 Filing 采集，但不得把 Official Notices 宣称为所有发行人财报和临时公告的完整替代。

### 去重与边界

- SIX Official Notice 使用官方 `noticeId` 建 canonical key；EQS 的瑞士发行人披露继续使用自身官方 ID，两者不得因 ID 数字相同而碰撞。
- MTF/其他交易场所若只是 SIX 上市证券的路由，不创建第二个 issuer master；其 venue/routing 覆盖另行统计。
- 保留未覆盖项：历史退市证券、非 SIX 发行人主目录、完整 ETF 专属披露、所有发行人财报/临时披露对账。

## 离线与在线验收

- 离线 fixture 覆盖 SA/AA/SP/ETF、SP 多币种同 ISIN、未知类型、分页、总数漂移、跨页重复、页数上限、非 JSON、403、详情冲突、单/多/非 ISIN 值及零命中。
- 真实只读抽样输出四个 scope 数量、instrument type 数量、源有效时间范围；SP 不得少于已设安全下限。
- 真实公告窗口输出列表总数、精确 ISIN 命中数，并证明零命中来自成功全量对账。
- 运行定向测试、相关回归、mypy 和 `git diff --check`。
- 最终报告必须列出修改前后、官方 URL、请求合同、字段映射、失败保护、量化结果、每日更新路径、仍然缺少的覆盖和 Git 提交信息。

## Git 边界

提交前检查工作树，只暂存本批明确修改和新增的瑞士文件。不得暂存既有未跟踪文档、用户附件或其他批次文件；提交并推送到 `ai功能测试`。
