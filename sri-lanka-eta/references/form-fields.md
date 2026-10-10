# ETA 表单字段完整映射

## 页面流程

| 步骤 | 操作 | 技术细节 |
|------|------|----------|
| 1. 条款 | 点击 I Agree | `input[name="terms"][value="yes"]` onclick 自动提交 |
| 2. 类别 | Tourist → Individual | `a#1` (id="1") |
| 3. 表单 | 填写所有字段 | 见下方 |
| 4. Next | 提交表单 | `input#submitButton` onclick=`valIndformone(this)` |
| 5. Review | 确认信息 | 仅展示，需人工确认 |

## 表单字段

### 基本信息

| 字段 | ID/Name | 类型 | 备注 |
|------|---------|------|------|
| Surname | `#surname` | input | |
| Other Names | `#othernames` | input | |
| Title | `#title` | select | `01\|MR` `02\|MRS` `03\|MISS` `04\|MS` `05\|MASTER` `06\|REV` `07\|DR` |
| Date of Birth | `#bdate` | input(readonly) | DD/MM/YYYY，自定义日历，需 JS 注入 |
| Re Enter DOB | `#reenteredbdate` | input(readonly) | 同上 |
| Gender | `#gender` | select | `Male` / `Female` |
| Nationality | `#national` | select | `CHN\|CHINA` 格式 |
| Country of Birth | `#conbirth` | select | 同上 |
| Occupation | `#occupation` | input | |

### 护照

| 字段 | ID/Name | 类型 | 备注 |
|------|---------|------|------|
| Passport No | `#passportno` | input | 含 0/1/O/I/L 字符可能触发 alert |
| Re Enter PP | `#reenteredpassportno` | input | |
| Issued Date | `#pidate` | input(readonly) | DD/MM/YYYY，需 JS 注入 |
| Expiry Date | `#pedate` | input(readonly) | 同上 |

### 未成年人（DOB < 16岁时出现）

- `childenable` checkbox: 不勾选 = 独立护照
- 勾选后需填写父母信息

### 旅行信息

| 字段 | ID/Name | 类型 | 备注 |
|------|---------|------|------|
| Departure Country | `#fromDeparture` | select | **必填**，漏填提交失败 |
| Visa Days | `#RequestedVisaDays` | select | `30`，触发 confirm 弹窗 |
| Arrival Date | `#iadate` | input(readonly) | DD/MM/YYYY |
| Purpose | `#puofvisit` | select | `V01\|Sightseeing or Holidaying` 等 |
| Port of Departure | `#depcity` | input | |
| Airline | `#airline` | input | 可选 |
| Flight No | `#flightno` | input | 可选 |

### 联系方式

| 字段 | ID/Name | 类型 | 备注 |
|------|---------|------|------|
| Address Line 1 | `#addone` | input | 必须用 click+type |
| Address Line 2 | `#addtwo` | input | 可选 |
| City | `#city` | input | 必须用 click+type |
| State | `#state` | input | 必须用 click+type |
| Zip Code | `#zipcode` | input | 可选 |
| Country | `#adcountry` | select | `CHN\|CHINA` |
| Address in SL | `#addinsl` | textarea | **必须用 click+type** |
| Email | `#email` | input | |
| Re Enter Email | `#reenteremail` | input | |
| Telephone | `#telephon` | input | |
| Mobile | `input[name="mobile"]` | input | 可选 |
| Fax | 无 | input | 可选 |

### 声明

| 字段 | Name | 值 |
|------|------|-----|
| 有效居留签？ | `QN1` | `0`=No `1`=Yes |
| 在斯里兰卡？ | `QN2` | `0`=No `1`=Yes |
| 多次入境签？ | `QN3` | `0`=No `1`=Yes |
| 确认勾选 | `conf` | checkbox |

## 弹窗类型

| 触发 | 类型 | 内容 |
|------|------|------|
| Visa Days = 30 | confirm | "...ETA once issued is valid for 30 days..." |
| 无效 Departure Country | alert | "Please Select Your Departure Country" |
| 地址为空 | alert | "Please Insert Address in Address Line 1" |
| SL 地址为空 | alert | "Please Insert a valid Address in Sri Lanka" |
| 护照号含 L/I/O/0/1 | alert | 字符确认 |
