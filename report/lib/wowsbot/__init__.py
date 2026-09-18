"""wowsbot —— bot 的公共层(路径/回放元数据/主题/文本/翻译/结算字段)。

故意留空:不在这里 re-export 子模块,避免 `from wowsbot import paths` 牵连加载
i18n(要读 .mo)、results(要读 constants.json)等有 I/O 的模块。
用法一律 `from wowsbot import paths` / `from wowsbot.theme import GAME_BG`。
"""
