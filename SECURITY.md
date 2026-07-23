# 安全说明

## 支持范围

| 版本 | 状态 |
| --- | --- |
| `v2.0.x` | 接收安全与稳定性修复 |
| `v1.x` | 仅接收高影响安全修复，建议升级 |
| 更早版本 | 仅尽力支持，建议升级 |

## 私下报告安全问题

请使用仓库 Security 页面中的 **Report a vulnerability** 私下提交安全报告：

<https://github.com/chenhaoxiang05/LightNovelSelector/security/advisories/new>

请包含：

- 受影响版本或提交；
- 可重复的最小步骤；
- 实际影响和预期行为；
- 已去除隐私信息的日志或截图；
- 你认为可行的缓解方式。

在问题修复并发布前，请勿创建公开 Issue、公开利用细节或上传真实小说文件。维护者会尽快确认收到报告，并在能够可靠复现后说明后续处理计划。

## 数据与隐私边界

LightNovelSelector 在本地读取文件名、必要的内容提示和完整文件指纹，用于生成分类计划、识别重复项和执行撤销。开启在线识别时，只发送标题或系列查询，不上传小说文件。

安全报告中请删除真实用户名、绝对目录、访问令牌、小说正文和私人分类记录。若问题仅涉及普通功能异常，请改用 [Bug 报告](https://github.com/chenhaoxiang05/LightNovelSelector/issues/new?template=bug_report.yml)。
