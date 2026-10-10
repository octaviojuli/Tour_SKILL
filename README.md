# Tour_SKILL

旅游 B2B 业务用到的各种技能（Skill），每个技能一个目录，目录里的 `SKILL.md` 是入口。

## 技能索引

| 技能 | 目录 | 作用 |
|---|---|---|
| tour-route-parser | [`tour-route-parser/`](tour-route-parser/) | 把供应商行程附件（PDF/DOCX）整理成带原文依据的线路 JSON、详情页和审核报告，供人工审核后发布 |
| sri-lanka-eta | [`sri-lanka-eta/`](sri-lanka-eta/) | 用 Playwright 自动填写斯里兰卡 ETA 旅游个人签证表单，停在 Review 页由人工确认 |

## 新增技能

1. 在仓库根目录新建一个目录，目录名与 `SKILL.md` 里的 `name` 一致。
2. 目录里至少放 `SKILL.md`（含 `name` 和 `description`）。
3. 在上面的索引表里补一行：技能名、目录链接、一句话作用。

## 注意

这是公开仓库，不要提交：

- 密钥、`.env`、模型配置文件；
- 供应商的原始附件和解析输出；
- 真实的申请人护照、联系方式等个人信息（技能里的 `payload.json` 只放示例占位数据）。
