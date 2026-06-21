# Bot Menu, Commands & Settings — Reference

Specification of the bot's menus, commands, and settings/access-control model —
the canonical structure every surface conforms to. Audience: deployer/owner and
contributors. Open work: `TODO.md`.

**Conventions.**

- **EN / RU** — every command and item carries both labels; EN is canonical, RU
  is the translation.
- **Access** — 🟢 *chat+* (any allowlisted user + owner) · 🟦 *code* (code-level +
  owner) · 👑 *owner*. Non-allowlisted users cannot reach the bot; the floor is
  *chat+*.
- **Keyboard tables** — one table row = one row of buttons; a full-width label
  sits in the first cell, marked `▮ full width`.
- **Tables are numbered** (`Table N`, sequential) for cross-reference.

---

## 1. Menu design guidelines

These rules apply to **every** menu. New menus follow them; existing ones are
aligned over time.

### 1.1 Button labels

- **Keep labels short.** A label competes for a narrow phone screen. Target
  **≤ 16 characters** for a button that shares its row with others, and
  **≤ ~24 characters** for a full-width button. Longer text wraps or is truncated
  with `…` on small devices.
- **One leading emoji, then a space, then the word(s).** Never more than one
  emoji per label. The emoji is the scannable anchor (see §1.3).
- **Value rows** use the pattern `«<emoji> <Name>: <value> ▸»` — the trailing
  `▸` signals "opens a sub-menu/picker".
- **A settings row NEVER changes its value in place — it always opens a picker.**
  This holds even for a boolean (a 2-option On/Off picker) or a single-option
  setting: tapping a row shows the choices first, with a **Back** button to leave
  without changing anything, so the user is never surprised by a silent flip and
  always sees how many values exist (#275). (A direct typed command like `/shell`
  or `/auto` still toggles immediately — that is explicit user intent, not a menu
  tap.)
- **Localized.** The visible text comes from the locale catalog; the same button
  is `«✏️ Rename»` / `«✏️ Переименовать»`. Slugs and callback tokens stay ASCII.

### 1.2 Layout by menu type

Buttons per row depends on label length and menu purpose.

**Table 1 — Buttons per row, by menu type.**

| Menu type | Buttons per row | Why |
|---|---|---|
| **Lists** (sessions, users) | **1 per row**, full width | the label is a name and needs the full width; the row *is* the item |
| **Setting rows** (the settings hub) | **1 per row**, full width | each row is `«Name: value ▸»` — too long to pair |
| **Actions with text labels** | **2 per row** | e.g. `Recap | Status`, `Rename | Favorite` |
| **Actions, short or emoji-only** | **2–3 per row** | e.g. `◂ Prev | Next ▸`, pickers |
| **Choice pickers** (model, effort, language) | **3 per row** | choices are short words |
| **Confirmations** | **2 per row** | `Confirm | Cancel` |
| **Navigation/footer** (search, close, new) | **2–3 per row**, last row | global actions grouped at the bottom |

Hard limits to respect: an inline keyboard may have many buttons, but **on mobile
only 2–3 text buttons per row stay readable**. Put the primary action first
(top-left), destructive actions (🗑) on their own row paired with `◂ Back`, and
`✖ Close` last.

### 1.3 Emoji vocabulary

One concept = one emoji, used identically on every surface.

**Table 2 — Emoji vocabulary (canonical set).**

| Emoji | Concept | | Emoji | Concept |
|---|---|---|---|---|
| 💬 | chat session | | 🔍 | search |
| 🟩 | code session | | ✖ | close |
| ➕ | new / add | | ◂ ▸ | back / forward · "opens" |
| 🗂 | sessions list | | ✅ | switch / allow / confirm |
| ⚙️ | settings | | ⛔ | deny |
| 🧠 | model | | ⏹ | stop |
| ⚡ | effort | | 🍴 | fork |
| 🔐 | permissions | | 📋 | recap |
| 🔁 | max turns | | ℹ️ | status |
| 🗄 | memory / context | | ✏️ | rename |
| 🧪 | sandbox | | 📄 | transcript / export text |
| 🌐 | language | | 📦 | export files (zip) |
| 📊 | usage / day limit | | ⭐ ☆ | favorite / unfavorite |
| 🧰 | tools | | 🗑 | delete / remove |
| 👥 | users | | ⏳ | access expiry |
| 👑 | owner / admin | | 📅 | week limit |
| 🚀 | auto-approve on | | ♾ | unlimited |

Notes: **🧠 is reserved for *model*** and **🗄 for *memory/context*** (these two
must not share an icon); **🧪 is *sandbox*** and **📦 is *file export*** (kept
distinct). The settings hub and the user-admin cards use the same icon for the
same concept.

### 1.4 Menu lifecycle & dismissal

A menu is a single editable message. It must never pile up stale copies in the
chat.

- **Navigation within a menu edits the *same* message** (tab switch, open a
  picker, go back) — no new message is sent.
- **Applying a value edits the message in place** and shows a short toast
  (`✓ Saved`). The keyboard re-renders with the new value/✓ mark.
- **Close deletes the menu message.** If deletion fails (too old), edit it to a
  short "closed" line so no live keyboard is left behind.
- **An action that posts content** (recap, transcript, export) sends the content
  and then **re-posts the menu at the bottom and deletes the previous menu
  message**, so there is always exactly one live menu and it is reachable without
  scrolling.
- **One live menu per surface.** Opening `/settings` or `/sessions` again replaces
  rather than stacks.

### 1.5 Arguments & input capture

Telegram **sends a tapped command immediately**, with no opportunity to append
arguments, and ~90% of use is on a phone. Therefore:

- **There are no optional arguments.** A command is either **argument-free** or it
  takes a **mandatory** argument.
- **Argument-free commands** act immediately, or open a picker when the input is a
  fixed set of choices (model, effort, language, permissions, usage, …).
- **Commands that need free text** (a name, a date, a token amount, a user id)
  **prompt and capture the user's *next* message** as the argument, with
  **`/cancel`** to abort. They never fail with a "usage:" error on an empty
  argument.
- **Fixed-choice input is always a picker, never typed** — including booleans,
  which open a 2-option On/Off picker with Back rather than flipping in place
  (#275). Free-text input is always next-message capture. (Typing `«/model opus»`
  still works as a power-user shortcut, but the menu path never requires it.)

### 1.6 The Telegram command list (the "/" menu)

Telegram's command list (the blue **menu** button / typing `/`) is only practical
for the **first few entries** — on a phone the top **1–3** are one tap away and
roughly the top 5 are reachable before scrolling becomes tedious. Consequences:

- **Commands are registered in frequency order**, most-used first, so the menu
  button surfaces what matters (see the ranking in §2).
- **Keep the prominent set small.** The everyday trio — `/new`, `/sessions`,
  `/settings` — sits at the very top. Rarer commands remain fully usable by typing
  and through the inline menus, but are not relied on from the menu button.
- **The list is filtered by role.** A chat-level user's `/` menu omits code-only
  and owner-only commands; the owner's private chat adds the owner block at the
  end (§1.8).

### 1.7 Chat and code sessions are one thing

A **chat** session and a **code** session are the *same* session with different
**available tools**, **context size**, and **privileges** — not two separate
products. A session is born as chat and is promoted/demoted in place (`/code`,
`/chat`), carrying its conversation across.

Consequences for menus and settings:

- **Every chat setting is also relevant to code.** Settings are presented
  uniformly for both.
- **Some settings are code-only** and are explicitly flagged as such (they need a
  working directory or the agent toolset): permissions, max turns, tools, the file
  commands. These rows simply do not appear in a chat session. (Sandbox is **not**
  code-only — the jail now covers chat sessions too, so its owner-only row shows in
  both chat and code.)
- The settings hub and pickers look identical in both; code merely shows
  additional, clearly-marked rows.

### 1.8 Admin parity

**The owner sees the same menus as everyone else.** Owner-only controls are
**appended at the end** of the relevant menu rather than living in a separate
admin app:

- In the **settings hub**, the owner sees the standard rows, then a `🌍 Global`
  scope tab and owner-only rows (e.g. 🧪 Sandbox, 📊 Usage display) and a final
  `👥 Users` entry.
- In any menu, owner-only buttons are the **last** rows, above `✖ Close`.

This keeps one mental model: admin features are an *extension* of the user menu,
positioned consistently at the bottom.

---

## 2. Commands — ranked by frequency

Most-used first — also the registration order in Telegram's `/` menu (§1.6). Each
row gives the EN/RU label, invocation, argument behaviour (§1.5), and access (the
Conventions legend).

### Tier A — Everyday (top of the "/" menu)

**Table 3 — Tier A · everyday commands.**

| Command | EN label | RU label | Args | Access |
|---|---|---|---|---|
| `/new` | ➕ New session (starts as chat) | ➕ Новая сессия (создаётся как чат) | prompts for a name (capture) | 🟢 |
| `/sessions` | Browse / switch / delete sessions | Обзор / переключение / удаление сессий | none → opens browser | 🟢 |
| `/settings` | Open the settings menu | Открыть меню настроек | none → opens hub | 🟢 |

### Tier B — Common

**Table 4 — Tier B · common commands.**

| Command | EN label | RU label | Args | Access |
|---|---|---|---|---|
| `/code` | 🟩 Upgrade this session to code | 🟩 Повысить сессию до кода | none | 🟦 |
| `/chat` | 💬 Downgrade this session to chat | 💬 Понизить сессию до чата | none | 🟢 |
| `/clear` (alias `/reset`) | Clear the session context | Очистить контекст сессии | none | 🟢 |
| `/retry` | Re-run the last prompt | Повторить последний запрос | none | 🟢 |
| `/status` | Current session info | Сведения о текущей сессии | none | 🟢 |

### Tier C — Occasional (mostly reached via the settings hub or session menu)

**Table 5 — Tier C · occasional commands.**

| Command | EN label | RU label | Args | Access |
|---|---|---|---|---|
| `/model` | Switch model: opus \| sonnet \| haiku | Сменить модель: opus \| sonnet \| haiku | none → picker | 🟢 |
| `/effort` | Reasoning depth: low … max | Глубина рассуждений: low … max | none → picker | 🟢 (`max` gated) |
| `/memory` | 1M context window (chat): on \| off | Окно контекста 1M (чат): on \| off | none → toggle | 🟢 |
| `/language` | Choose the interface language | Выбрать язык интерфейса | none → picker | 🟢 |
| `/context` | Context-window usage | Использование окна контекста | none | 🟢 |
| `/limits` | 📊 Your usage limits | 📊 Ваши лимиты использования | none | 🟢 |
| `/queue` | Show the pending-prompt queue | Показать очередь запросов | none | 🟢 |
| `/clearqueue` | Clear the pending queue | Очистить очередь | none | 🟢 |
| `/rename` | Rename the current session | Переименовать текущую сессию | prompts for a name (capture) | 🟢 |
| `/recap` | 📋 Recap the session in one line (AI) | 📋 Краткая сводка сессии в одну строку (ИИ) | none → runs a model turn | 🟢 |
| `/last` | Show the last exchange (verbatim) | Показать последний обмен (как есть) | none | 🟢 |
| `/history` | Export this session's transcript | Выгрузить расшифровку этой сессии | none | 🟢 |
| `/fork` | Branch this session into a new one | Ответвить эту сессию в новую | none | 🟢 |

### Tier D — Code-only (🟦)

**Table 6 — Tier D · code-only commands.**

| Command | EN label | RU label | Args | Access |
|---|---|---|---|---|
| `/files` | Browse the working-dir tree (code) | Дерево рабочей папки (код) | none | 🟦 |
| `/export` | Export working-dir files as .zip (code) | Экспорт файлов рабочей папки (.zip, код) | none | 🟦 |
| `/maxturns` | Cap agentic turns (code) | Лимит агентных ходов (код) | none → picker | 🟦 |
| `/permissions` | Code tool policy: auto-edits · plan · full-access | Политика инструментов кода: auto-edits · plan · full-access | none → picker | 🟦 |
| `/tools` | Configure this session's tools | Настроить инструменты сессии | none → grid | 🟦 |
| `/secret` | 🔐 Set a per-session service credential (code) | 🔐 Учётные данные сервиса для сессии (код) | prompts (capture) | 🟦 |
| `/shell` | ⌨️ Toggle a persistent jailed shell — cd/env persist, interactive prompts get a key keypad; toggle = detach (code) | ⌨️ Постоянный shell в песочнице — cd/env сохраняются, интерактив с клавиатурой-кнопками; переключение = detach (код) | none → toggle | 🟦 |

### Tier E — Meta & secondary

**Table 7 — Tier E · meta & secondary commands.**

| Command | EN label | RU label | Args | Access |
|---|---|---|---|---|
| `/help` (`/start`) | Show help | Показать справку | none | 🟢 |
| `/whoami` | Show your id and username | Показать ваш id и username | none | 🟢 |
| `/usage` | Subscription-usage display | Показ использования подписки | none → picker | 🟢 view · 👑 change |
| `/cancel` | Cancel a pending prompt-capture | Отменить ввод аргумента | none | 🟢 |
| `/newchat` | 💬 New chat session | 💬 Новая чат-сессия | prompts for a name | 🟢 |
| `/newcode` | 🟩 New code session | 🟩 Новая код-сессия | prompts for a name | 🟦 |
| `/mode` | Switch session type (alias of /code, /chat) | Сменить тип сессии (синоним /code, /chat) | none | 🟢 |
| `/close` | Close (delete) the current session | Закрыть (удалить) текущую сессию | none | 🟢 |

### Tier F — Owner (👑, appended to the owner's menu only)

**Table 8 — Tier F · owner commands.**

| Command | EN label | RU label | Args | Access |
|---|---|---|---|---|
| `/users` | List allowed users (owner) | Список пользователей (владелец) | none → cards | 👑 |
| `/userstats` | 📊 User usage stats — table (owner) | 📊 Статистика пользователей — таблица (владелец) | none → table | 👑 |
| `/allow` | Allow a user (owner) | Разрешить пользователя (владелец) | prompts (capture) | 👑 |
| `/deny` | Remove a user (owner) | Удалить пользователя (владелец) | prompts (capture) | 👑 |
| `/level` | Set a user's access level (owner) | Уровень доступа (владелец) | prompts (capture) | 👑 |
| `/expire` | Set a user's access expiry (owner) | Срок доступа (владелец) | prompts (capture) | 👑 |
| `/limit` | Top up a user's token grant (owner) | Пополнить лимит токенов (владелец) | prompts (capture) | 👑 |
| `/auto` | Run code tools without asking (owner) | Запускать инструменты кода без вопросов (владелец) | none → toggle | 👑 |
| `/codesplit` | Code blocks as separate messages: on/off (owner) | Блоки кода отдельными сообщениями: on/off (владелец) | none → toggle | 👑 |
| `/workingplate` | ⏳ Working/Stop plate: on \| off (owner) | ⏳ Плашка Working/Stop: on \| off (владелец) | none → toggle | 👑 |
| `/sandbox` | Toggle this session's sandbox — applies to all sessions, chat & code (owner) | Песочница сессии вкл/выкл — для всех сессий, чат и код (владелец) | none → toggle | 👑 |

> **Not commands:** a plain message is a prompt to the current session; a photo,
> PDF, or text/code file uses its caption as the prompt. Messages sent while a
> reply is running are queued and run next in the same session.

---

## 3. Menu surfaces — how they appear in Telegram

Each surface below shows its keyboard as a layout table (one table row = one
keyboard row) plus a reference of labels and access.

### 3.1 The "/" command menu

Rendered by Telegram from the registered command list, filtered by role and shown
in frequency order. A chat-level user sees Tiers A–C + E (minus code-only); a
code-level user adds Tier D; the owner adds Tier F at the end.

**Table 9 — The "/" command menu (top entries).**

| `/` menu (phone, top entries) |
|---|
| `/new` — ➕ New session (starts as chat) |
| `/sessions` — Browse / switch / delete sessions |
| `/settings` — Open the settings menu |
| `/code` — 🟩 Upgrade this session to code |
| `/chat` — 💬 Downgrade this session to chat |
| … (remaining commands, scrollable) |

### 3.2 The settings hub (`/settings`)

One hub with **scope tabs** at the top; one full-width row per setting (§1.2).
Owner-only rows and the `🌍 Global` tab are appended at the end (§1.8). Code-only
rows appear only in a code session (§1.7).

**Table 10 — Settings hub keyboard.**

| Settings hub — keyboard | (col 2) |
|---|---|
| 📍 This session | 👤 My defaults · 🌍 Global (👑) |
| 🧠 Model: opus · this session ▸ | ▮ full width |
| ⚡ Effort: high ▸ | ▮ full width |
| 🔐 Permissions: auto-edits ▸ *(code)* | ▮ full width |
| 🔁 Max turns: unlimited ▸ *(code)* | ▮ full width |
| 🗄 Big memory: off *(granted)* | ▮ full width |
| 🧪 Sandbox: on ▸ *(owner)* | ▮ full width |
| 🌐 Language: English ▸ | ▮ full width |
| 🔥 Warm-cache note: off | ▮ full width |
| 📦 Auto-compact: on | ▮ full width |
| 🧠 Live context size: on | ▮ full width |
| 🧰 Tools ▸ *(code)* | ▮ full width |
| 📊 Usage display ▸ *(owner)* | ▮ full width |
| 👥 Users ▸ *(owner)* | ▮ full width |
| 👑 Admin ▸ *(owner)* | ▮ full width |
| ✖ Close | ▮ full width |

**Table 11 — Settings hub rows.**

| Tab / row | EN | RU | Access |
|---|---|---|---|
| Tab | 📍 This session · 👤 My defaults · 🌍 Global | 📍 Эта сессия · 👤 Мои умолчания · 🌍 Глобально | 🟢 / 🟢 / 👑 |
| Model | 🧠 Model: {value} ▸ | 🧠 Модель: {value} ▸ | 🟢 |
| Effort | ⚡ Effort: {value} ▸ | ⚡ Усилие: {value} ▸ | 🟢 (`max` gated) |
| Permissions | 🔐 Permissions: {value} ▸ | 🔐 Права: {value} ▸ | 🟦 |
| Max turns | 🔁 Max turns: {value} ▸ | 🔁 Лимит ходов: {value} ▸ | 🟦 |
| Big memory | 🗄 Big memory: {on/off} | 🗄 Большая память: {вкл/выкл} | 🟢 (granted) |
| Sandbox | 🧪 Sandbox: {value} ▸ | 🧪 Песочница: {value} ▸ | 👑 |
| Language | 🌐 Language: {name} ▸ | 🌐 Язык: {name} ▸ | 🟢 |
| Warm-cache note | 🔥 Warm-cache note: {on/off} | 🔥 Заметка о тёплом кэше: {вкл/выкл} | 🟢 (delegated) |
| Auto-compact | 📦 Auto-compact: {on/off} | 📦 Автокомпакт: {вкл/выкл} | 🟢 (forced-on; owner delegates to disable) |
| Live context size | 🧠 Live context size: {on/off} | 🧠 Размер контекста в плашке: {вкл/выкл} | 🟢 (forced-on; owner delegates to disable) |
| Tools | 🧰 Tools ▸ | 🧰 Инструменты ▸ | 🟦 |
| Usage display | 📊 Usage display ▸ | 📊 Использование ▸ | 👑 |
| Users | 👥 Users ▸ | 👥 Пользователи ▸ | 👑 |
| Admin | 👑 Admin ▸ | 👑 Админ ▸ | 👑 |
| Close | ✖ Close | ✖ Закрыть | 🟢 |

A value row opens a **picker** (3 choices per row, §1.2) with a ✓ on the current
value and a `◂ Back` that returns to this hub. A bool row toggles in place. The
scope badge next to a value (`this session` / `my default` / `global default`)
names where the effective value comes from (§4).

The **👑 Admin** row (owner only) opens a sub-page that consolidates owner controls
not surfaced as their own hub rows: the **🗄 Archive retention** picker (#178 —
purge deleted-session bundles older than 1 / 3 / 6 / 12 months or Never; default
6 months), the global owner toggles **🧩 Code split** and **⏳ Working plate**, and
quick launchers for the user-management commands (**➕ Allow · ➖ Deny · 🎚 Level ·
⏳ Expiry · 💳 Tokens · 📊 Stats**). Each launcher starts the matching command's
arg-capture (§1.5) or opens its page.

### 3.3 The sessions browser (`/sessions`)

A list — **one session per row** (§1.2), favorites first and marked. Tapping a
session opens its action menu. Global actions are grouped in the footer.

**Table 12 — Sessions browser keyboard.**

| Sessions browser — keyboard | (col 2) |
|---|---|
| ⭐ 💬 My chat session | ▮ full width |
| 🟩 Build script | ▮ full width |
| … | |
| ◂ Prev | Next ▸ |
| 💬 New chat | 🟩 New code *(code)* |
| 🔍 Search | ✖ Close |

**Table 13 — Session action menu keyboard** *(code session shown).*

| Session action menu — keyboard | (col 2) |
|---|---|
| ✅ Switch | ▮ full width |
| 📋 Recap *(AI, one line)* | ℹ️ Status |
| ✏️ Rename | ⭐ Favorite / ☆ Unfavorite |
| 📄 Transcript | ▮ full width |
| 💬 Convert to chat | 📦 Export files *(code)* |
| 🗑 Delete | ◂ Back |

**Convert / Export pairing.** 🟩/💬 *Convert* no longer takes a full-width high
row: it sits LOW and pairs with another action. In a **code** session it pairs with
📦 *Export files* (`💬 Convert to chat | 📦 Export files`); in a **chat** session
there is no Export, so 🟩 *Convert to code* pairs with 📄 *Transcript*
(`📄 Transcript | 🟩 Convert to code`) and appears only if the session owner has
code access. **📋 Recap runs the AI one-line recap** (a model turn); the verbatim
last prompt+reply is the `/last` command, not a menu button.

**Table 14 — Session action buttons.**

| Button | EN | RU | Access |
|---|---|---|---|
| Switch | ✅ Switch | ✅ Переключиться | 🟢 |
| Convert to code | 🟩 Convert to code | 🟩 Сделать кодом | 🟦 |
| Convert to chat | 💬 Convert to chat | 💬 Сделать чатом | 🟢 |
| Recap | 📋 Recap *(AI one-line recap — runs a model turn)* | 📋 Сводка *(сводка от ИИ — запускает ход модели)* | 🟢 |
| Status | ℹ️ Status | ℹ️ Статус | 🟢 |
| Rename | ✏️ Rename | ✏️ Переименовать | 🟢 |
| Favorite | ⭐ Favorite / ☆ Unfavorite | ⭐ В избранное / ☆ Из избранного | 🟢 |
| Transcript | 📄 Transcript | 📄 Транскрипт | 🟢 |
| Export files | 📦 Export files | 📦 Экспорт файлов | 🟦 |
| Delete | 🗑 Delete | 🗑 Удалить | 🟢 |
| Back | ◂ Back | ◂ Назад | 🟢 |
| New chat / code | 💬 New chat · 🟩 New code | 💬 Новый чат · 🟩 Новый код | 🟢 / 🟦 |
| Search / Close | 🔍 Search · ✖ Close | 🔍 Поиск · ✖ Закрыть | 🟢 |

### 3.4 User-admin cards (👑)

Opened from the settings hub `👥 Users` entry. The list shows one user per row
(owner first); tapping one opens that user's card. Per §1.8 these are the deepest
owner-only surface. They are where the owner sets each user's **access exceptions**
(the **🔑 Access** sub-page — per §4) and **resource quotas**.

**Table 15 — User card keyboard.**

| User card — keyboard | (col 2) | (col 3) |
|---|---|---|
| Level: chat → code | 🔢 Sessions: default | |
| 🗄 Memory: on | ⚡ Max effort: off | |
| 🧰 Tools: all | 🔑 Access | |
| ✏️ Friendly name… | ⏳ Set expiry… | |
| 📊 Day limit… | 📅 Week limit… | ⏳ Idle: default |
| ♾ Clear limits | ▮ full width | |
| 🗑 Remove access | ▮ full width | |
| ◂ Users | | |

> **Owner self-limit card.** The owner has their own card too. It omits
> level / expiry / access / friendly-name / remove (the owner is always code,
> never expires, always full access, and can't self-remove) but exposes the same
> self-imposable limits for testing: **🗄 Memory · ⚡ Max effort · 🧰 Tools · ⏳ Idle ·
> 📊 Day limit · 📅 Week limit · 🔢 Sessions** (clear the limits to go back to
> uncapped).

**Table 16 — User card buttons.**

| Button | EN | RU |
|---|---|---|
| Level | Level: {level} → {next} | Уровень: {level} → {next} |
| Sessions | 🔢 Sessions: {value} | 🔢 Сессии: {value} |
| Memory | 🗄 Memory: {state} | 🗄 Память: {state} |
| Max effort | ⚡ Max effort: {state} | ⚡ Max effort: {state} |
| Tools | 🧰 Tools: {value} | 🧰 Инструменты: {value} |
| Access | 🔑 Access | 🔑 Доступ |
| Name | ✏️ Friendly name… | ✏️ Имя… |
| Expiry | ⏳ Set expiry… | ⏳ Срок доступа… |
| Idle | ⏳ Idle: {value} | ⏳ Простой: {value} |
| Day / Week limit | 📊 Day limit… · 📅 Week limit… | 📊 Лимит/день… · 📅 Лимит/неделя… |
| Clear limits | ♾ Clear limits | ♾ Снять лимиты |
| Remove | 🗑 Remove access → 🗑 Yes, remove | 🗑 Убрать доступ → 🗑 Да, убрать |
| Add | ➕ Add user | ➕ Добавить |
| Back | ◂ Users | ◂ Пользователи |

**🔑 Access sub-page (per-user exceptions).** Tapping **🔑 Access** opens one row per
option showing that user's effective access — their **exception** if set, else
*base: <the global base>*. Tapping an option offers **Base (inherit) · Delegated ·
Read-only · Hidden**. This is how *"give it to only some users"* is expressed:
**leave the base Hidden, then delegate per user here.**

> **Worked example — delegate 🗄 Big memory to specific users.** Big memory's base
> access is **Hidden** (Table 23), so by default no one but the owner sees it. To
> grant it to a chosen user: **👥 Users → tap the user → 🔑 Access → 🗄 Big memory →
> Delegated**. That user now sees and toggles big memory; everyone else still has it
> hidden. (If you previously changed its **Global** base to Read-only, set it back to
> **Hidden** on 🌍 Global → 🗄 Big memory → 🔑 Base access first.)

### 3.5 Choice pickers

Pickers present a fixed set of short choices, **3 per row** (§1.2), ✓ on the
current value, `◂ Back` to the parent. Used by `/model`, `/effort`, `/language`,
`/permissions`, `/usage`, `/maxturns`, and the equivalent settings-hub rows.

**Table 17 — Effort picker keyboard (example).**

| Effort picker — keyboard | | |
|---|---|---|
| low | medium | high |
| xhigh | ✓ max | default |
| ◂ Back | | |

**Table 18 — Choice pickers.**

| Picker | Choices | Access |
|---|---|---|
| Model | opus · sonnet · haiku | 🟢 |
| Effort | low · medium · high · xhigh · max · default | 🟢 (`max` gated) |
| Permissions | ask · auto-edits · plan · full-access | 🟦 (`full-access` 👑) |
| Usage display | off · footer · pinned · both | 👑 |
| Max turns | 10 · 25 · 50 · 100 · unlimited | 🟦 |
| Language | (each supported locale) | 🟢 |

### 3.6 Ephemeral menus

Short-lived keyboards attached to a specific message.

**Table 19 — Ephemeral menus.**

| Surface | Buttons (EN / RU) | Access |
|---|---|---|
| Queue | ✖ Cancel {i} / ✖ Отменить {i} · 🗑 Clear all / 🗑 Очистить всё | 🟢 |
| Live reply | ⏹ Stop / ⏹ Стоп | 🟢 (own run) |
| Permission request | ✅ Allow / ✅ Разрешить · ⛔ Deny / ⛔ Запретить | 👑 |

---

## 4. Settings & access-control model

One mechanism by which the **owner** governs what each user may see and change,
uniformly for every option (model, effort, permissions, tools, memory, language,
…) and for gated capabilities (code mode, `max` effort, `full-access`, a given
tool). Each option is **one row** in a master matrix (Table 23); effective values
are **computed per prompt**, not stored.

### 4.1 Concept

Each option is fully described by three things the owner controls:

1. **Global value** — the default, and the live value for everyone who has not
   overridden it.
2. **Base access level** — what all users get by default: *Hidden*, *Read-only*,
   or *Delegated*.
3. **Exceptions** — the users who differ from the base (e.g. delegated to a few
   named users while hidden from the rest).

Above these sit fixed rules, identical for all options.

### 4.2 Access levels

**Table 20 — Access levels (the master dictionary).**

| Level | User sees it | User can change it | Value for the user | Owner's global edits affect the user |
|---|---|---|---|---|
| **Hidden** | no | no | global (silently) | yes, always |
| **Read-only** | yes | no | global | yes, always |
| **Delegated** | yes | yes — own default + per session | own value (session → own default); until set, global | only until the user sets their own; after that, no |

This is the ladder: *grant it → let them use it · otherwise read-only · otherwise
they never see it.*

### 4.3 Value resolution order

**Table 21 — Where a value comes from (resolution order).**

| Priority | Layer | Set by | Counts when |
|---|---|---|---|
| 1 (highest) | session value | user | option is *Delegated* and the user set a value in this session |
| 2 | user's personal default | user | option is *Delegated* and the user set a personal default |
| 3 (base) | global | owner | always |

There is **no "owner sets a value for a specific user" layer** — if an option is
delegated, the user owns its value. The owner controls the *rules*, not the
values.

### 4.4 Owner capabilities

**Table 22 — What the owner can and cannot do.**

| Owner action | Allowed? |
|---|---|
| Change **global** (default for all; applies immediately to all sessions) | yes, anytime |
| Change an option's **access level** (Hidden / Read-only / Delegated) | yes, anytime |
| Change the **exceptions list** (who it is delegated to) | yes, anytime |
| Change a **user's personal default** | no |
| Change the **value in a specific session** | no |
| **Override** a user's value while the option is delegated to them | no |

Principle: **global is both the default and the live value** for everyone who has
not overridden it — change it and it applies instantly to every session that
relies on it. The owner manages rules and global, never reaches into a user's
values or an individual session. "Taking it back" = lowering the access level →
the effective value immediately falls back to global for all of that user's
sessions.

### 4.5 Master settings matrix

One row per option. *Applies to* marks code-only options (§1.7). *Base access* and
*Exceptions* are the owner's controls; *Global* is the current default.

**Table 23 — Master settings matrix.**

| Option | Type / values | Global | Applies to | Base access | Exceptions / gates |
|---|---|---|---|---|---|
| `model` | enum: opus, sonnet, haiku | opus | all | Delegated | — |
| `effort` | enum: low, medium, high, xhigh, max, default | high | all | Delegated | `max`: delegated only to granted users |
| `permission_mode` | enum: ask, auto-edits, plan, full-access | auto-edits | code | Delegated | `full-access`: owner only; default `auto-edits` auto-runs in-jail edits + ordinary shell, prompts only for push/destructive/web |
| `max_turns` | int 1–1000, or unlimited | unlimited | code | Delegated | — |
| `memory` | bool | off | all | Hidden | Delegated: granted users (the per-session 1M big-memory toggle) |
| `sandbox` | bool | on | all (chat & code) | Hidden | owner: Delegated (#180: jail covers chat sessions too) |
| `language` | enum: supported locales | en | all (UI) | Delegated | — |
| `usage_display` | enum: off, footer, pinned, both | footer | account-wide | Read-only | owner: Delegated |
| `hot_cache_timer` | bool | off | all | Delegated | every user may toggle their warm-cache note |
| `auto_compact` | bool | on | all | Hidden | forced-on (CLI default); owner: Delegated to disable |
| `ctx_status` | bool | on | all | Hidden | forced-on; owner: Delegated to disable (live context size in the working plate) |
| `tools` | multi-select (chat: web tools; code: full toolset) | all on | all (universe varies by type) | Delegated | per-user tool allow-list |

Reading the columns:

- **Base access** is what all users get by default — *Hidden*, *Read-only*, or
  *Delegated*.
- **Exceptions** are who differs, written as `level: users`. Empty = the same for
  everyone. This is how "given to all" vs "given to some" is expressed:
  *given to all* → base *Delegated*, no exceptions; *given to some* → base *Hidden*
  (or *Read-only*) with an exception `Delegated: …`.

**Resource quotas are a separate axis.** Per-user token caps (day/week), access
expiry, the per-user session limit (max-sessions), and the idle-TTL are *limits*,
not option values; they live on the user-admin card (§3.4) and are not part of this
matrix.

### 4.6 Standing rules

These are baked into the standard (and could be flipped if the model is ever
revised):

- **Soft revoke.** Lowering an option's access keeps the user's stored values but
  stops counting them — the effective value falls back to global. Restoring access
  brings the user's values back. Nothing is deleted.
- **Start of a delegated option.** Until the user sets their own value, they ride
  the current global (and follow the owner's edits to it). For full isolation from
  the moment of delegation, snapshot global into the user's personal default at
  delegation time.
- **Derived, not stored.** Effective values are **computed on each prompt** from
  the matrix — base access + exceptions for this user, then global → user default →
  per-session value (keyed by session id). No per-session "actual value" is
  persisted. The only stored data is: the owner's **global values + access levels +
  exceptions**, each user's **personal defaults**, and each session's **explicit
  overrides**. Because nothing effective is cached, any change the owner makes
  applies from the user's very next prompt.
