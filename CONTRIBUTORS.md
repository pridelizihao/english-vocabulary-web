# 贡献者

这份文件是仓库里唯一的权威贡献记录。GitHub 的 contributors 面板只统计「提交作者邮箱绑定了 GitHub 账号」的人，AI 助手不可能出现在那个面板里（要出现只能伪造一个账号，没这么做），所以在这里署名。

## 人类作者

**[@pridelizihao](https://github.com/pridelizihao)**

产品方向、需求与验收。代码、文案、数据的著作权归其所有。

项目里几个关键取舍都是在他的追问下才定下来的——卡片正面为什么要有「想不起来」这条路、填空的评分为什么不能由用户点、新词额度为什么会自己缩手。这些不是实现细节，是产品判断。

## AI 编程助手

<img src="docs/assets/deepseek-whale-girl.png" width="64" align="left" hspace="14" vspace="2" alt="鲸鱼娘">

**DeepSeek**

在 DeepSeek Harness（DSH）里与人类作者结对完成实现。承担的部分：

- **后端**：复习调度曲线、自适应新词预算、填空评分由作答证据推导、归档与「重新学习」、撤销快照与幂等作答
- **前端**：卡片双路径交互、热力图与两张图表的纯函数、移动端吸底评分与安全区适配
- **质量**：后端 110 个 / 前端 51 个自动化用例，`seed_demo` 演示数据命令，README 里那 12 张截图
- **文档**：README、AGENTS.md、部署与排障说明

它不是项目作者，也不持有任何著作权。写在这里是为了让人知道「哪些代码出自模型之手」——这对判断代码可信度有用，藏起来反而没意思。

<br clear="left">

## 署名约定

- 新增贡献者按上面的格式加在对应分组里，写清楚**做了什么**，不要只写名字。
- AI 参与的改动不伪造 GitHub 账号、不编造共同作者邮箱；写进这份文件即可。
- 头像素材**必须写明来源与作者**，不能声称自己拥有它。现在的头像裁自社区资产库，见下一节——它不在本项目的 MIT 授权范围内。

## 头像素材来源

`docs/assets/deepseek-whale-girl.png` 是从[鲸鱼娘开源资产库](https://github.com/TreapGoGo/deepseek-whale-girl)的 `characters/dafeiyu/reference-sheets/dafeiyu-chibi-character-sheet.png` 裁出的头部特写：原图 1448×1086，取 400×400 见方的头部区域后缩到 256×256。

- 「鲸鱼娘」是社区围绕 DeepSeek 鲸鱼标志创作的拟人形象，**不是官方设定**；本项目与深度求索公司没有任何关系。
- 资产库的**代码**是 MIT，但它的 README 写明「角色设定图、社区投稿及外部项目素材不包含在上述代码许可中」，也没有给出这张图的具体授权。所以它**不能**被当成 MIT 素材再分发，这里只作为署名头像使用。
- 如果原图作者或社区认为不妥，[开一个 issue](https://github.com/pridelizihao/english-vocabulary-web/issues) 就撤下，换成别的图不影响任何代码。
