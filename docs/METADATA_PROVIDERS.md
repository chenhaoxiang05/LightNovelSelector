# 元数据提供器开发指南

本指南说明如何为 LightNovelSelector 增加新的在线书库来源，而不修改分类、文件移动、
报告或撤销核心。

## 接口边界

每个来源继承 `MetadataProvider`，并声明四个稳定属性：

| 属性 | 作用 |
| --- | --- |
| `provider_id` | 小写稳定标识，只能包含字母、数字、下划线和连字符 |
| `display_name` | 显示在候选、详情和设置页中的名称 |
| `priority` | 数字越小越先查询；相同优先级保持注册顺序 |
| `cache_version` | 远程字段映射或结果语义变化时递增 |

`resolve_series()` 返回最可靠的系列结果，`resolve_book()` 可选返回单卷详情。没有可靠
结果时返回 `None`，不要用低质量候选填满字段。

```python
from lightnovel_selector import (
    BookIdentity,
    MetadataProvider,
    ResolveResult,
    acceptance_threshold,
    extract_series_guess,
    http_json,
    safe_folder_name,
    score_title,
)


class ExampleLibraryProvider(MetadataProvider):
    provider_id = "example-library"
    display_name = "Example Library"
    priority = 40
    cache_version = "1"

    def resolve_series(
        self,
        query: str,
        *,
        timeout: float,
    ) -> ResolveResult | None:
        data = http_json(
            "https://api.example.org/v1/books",
            payload={"query": query},
            timeout=timeout,
        )
        item = data.get("best")
        if not isinstance(item, dict):
            return None
        title = item.get("title")
        if not isinstance(title, str):
            return None
        confidence = score_title(query, title)
        if confidence < acceptance_threshold(query):
            return None
        return ResolveResult(
            identity=BookIdentity(
                title=title,
                series_name=safe_folder_name(extract_series_guess(title)),
            ),
            source=self.display_name,
            confidence=confidence,
            local_guess=query,
        )
```

核心会再次规范化 `BookIdentity`，把来源替换为注册显示名，把查询替换为当前查询，并限制
文本长度、作者/标签数量、卷号、语言、置信度与 HTTPS URL。提供器仍应尽早拒绝畸形
响应，以便错误信息能够准确定位。

## 显式注册

库调用方可以组合内置来源与第三方来源：

```python
from lightnovel_selector import (
    MetadataProviderRegistry,
    SeriesResolver,
    builtin_metadata_providers,
)

registry = MetadataProviderRegistry((*builtin_metadata_providers(), ExampleLibraryProvider()))
resolver = SeriesResolver(providers=registry)
```

同一注册表也可以传给 `build_classification_plan(metadata_providers=registry)` 或
`ApplicationService(metadata_providers=registry)`，从而覆盖扫描、候选和详情完整流程。

向主项目贡献内置来源时：

1. 在 `lightnovel_selector/providers/` 新建独立模块；
2. 复用 `http_json`、`validate_https_url`、标题评分和身份规范化函数；
3. 只在 `builtin_metadata_providers()` 中注册实例；
4. 不在 `classification.py`、`application.py` 或 `SeriesResolver` 中增加服务判断；
5. 更新中文文档，并增加提供器映射与异常测试。

## 缓存规则

缓存命名空间由按优先级排列的 `provider_id@cache_version` 生成。同一查询在不同来源组合
间不会串用缓存。每条记录还会绑定实际返回结果的 `provider_id`；读取缓存时会确认该
来源仍在当前注册表中，并重新执行身份、置信度和 URL 契约校验。来源被移除、记录损坏
或校验失败时会忽略缓存并重新查询。以下变化必须提升 `cache_version`：

- 标题选择或评分语义改变；
- 远程字段映射改变；
- 作者、标签、卷号或语言推断改变；
- 详情 URL、封面或简介来源改变。

只修复网络重试、日志文字或内部重构时不需要提升。

## 安全要求

- 只发送由文件名、用户规则或手动系列产生的查询，不发送小说正文、哈希、报告或绝对路径。
- 网络请求必须使用项目的受限读取函数，保留 HTTPS、公开地址、重定向和响应体积校验。
- 不记录访问令牌、Cookie、完整响应或用户查询之外的敏感数据。
- 对列表数量、嵌套深度和字符串长度设置上限，不信任第三方 JSON 类型。
- 单个来源失败时抛出普通异常或返回 `None`；不要终止进程、修改文件或自行重试无限次。
- 提供器只负责读取元数据，不能移动、删除、重命名或覆盖小说文件。

应用不会自动加载用户目录中的 `.py` 文件、环境变量模块或 Python entry point。提供器代码
与主程序拥有相同权限，因此只允许调用方显式注册或通过代码审查进入内置列表。

## 最低测试

新来源至少覆盖：

- 正常系列匹配和拒绝低置信度候选；
- 书籍详情映射（如果实现）；
- 缺失字段、错误类型、空列表和超大列表；
- 超时、HTTP 错误与部分来源失败；
- 非 HTTPS、内网或畸形封面/详情 URL；
- 作者、标签、卷号、语言和置信度边界；
- `cache_version` 变化后的缓存隔离。

提交前执行仓库 [开发说明](../DEVELOPMENT.md) 中的完整验证命令。
