# ADR-058: Discord Crew Card — Terminal-Chic Design System

**Status:** Accepted  
**Date:** 2026-05-02  
**Author:** adonisja

---

## Context

After finalization, each truck's Discord channel receives a crew assignment card posted by the bot. Multiple iterations of this card were attempted (plain-text code blocks, multi-field inline embeds, backtick pill grids) before arriving at a stable design that renders correctly across Discord desktop, iOS, and Android.

The key constraints:
- Discord embed fields have a hard limit of **25 fields** — any layout that uses one field per name hits this immediately with large crews.
- Emoji inside monospace code blocks render as **double-width** characters on Discord, breaking column alignment.
- Space-padding inside backtick inline code **does** produce fixed-width pills in Discord's monospace font — this is the correct mechanism for aligned two-column grids.
- The bot is a plain Python process — **it does not hot-reload**. Any code change requires a container restart.

---

## Decision

### Visual Design: "Terminal-Chic"

The crew card uses a single Discord embed with `color=0x5865F2` (Discord blurple left accent). All sections are `inline=False` fields. The visual aesthetic combines:

- **Monospace font** via backtick inline code for name pills
- **High-contrast** white text on dark Discord background
- **ASCII dash dividers** (`------------------------------------------`) for section separation
- **Bold labels** (`**Driver:**`, `**Walkers:**`) for hierarchy
- **Fixed-width columns** via right-padding names with spaces inside backticks

### Layout Structure

```
`         Eagle          `        ← wide centered pill, NO divider above
------------------------------------------   ← single divider below name

📋 Crew Leadership                           ← embed field name (bold)
**Driver:** `Danny Driver`

**Trainers:**
`Andre Williams ` `Keisha Simmons `          ← fixed-width pills, two per row

------------------------------------------
**Walkers:**
`River Daniels  ` `Cameron Bell   `
`Remy Hawkins   ` `Jolene Caine   `
...
`Bex Warfield   ` `Seren Blackwood`          ← even count, no empty pill
`Tess Drummond  `                            ← odd count gets one pill only
                                              (no empty right pill for walkers)

------------------------------------------
**Trainees:**
`Timmy Trainee  ` `               `          ← odd count: empty right pill rendered

------------------------------------------
Dispatch date: 2026-05-03                    ← footer
```

### Key Implementation Details

**Truck name pill width:**
```python
HEADER_WIDTH = 34  # total chars inside pill — produces ~75% card width
padded_name = f"{truck_name:^{HEADER_WIDTH}}"
embed.add_field(name="​", value=f"`{padded_name}`\n{SEP}", inline=False)
```
- No divider above the name pill — it sits at the top of the embed body
- Single divider immediately below

**Fixed-width name columns:**
```python
COL = 16  # characters per pill — right-pads shorter names with spaces

def pills_paired(names):
    lines = []
    for i in range(0, len(names), 2):
        pair = names[i:i + 2]
        left  = f"`{pair[0]:<{COL}}`"
        right = f"`{pair[1]:<{COL}}`" if len(pair) == 2 else f"`{'':< {COL}}`"
        lines.append(f"{left} {right}")
    return "\n".join(lines)
```
- `:<{COL}` right-pads with spaces so both columns are always equal width
- The empty right pill (`\`               \``) is rendered for odd-count sections to keep the grid visually consistent

**Section structure (field count = 4 max, never hits Discord's 25 limit):**
```python
# 1. Truck name + divider
embed.add_field(name="​", value=f"`{padded_name}`\n{SEP}", inline=False)

# 2. Crew Leadership (driver + trainers in one field, blank line between)
leadership = f"**Driver:** `{driver}`"
if trainers:
    leadership += f"\n\n**Trainers:**\n{pills_paired(trainers)}"
embed.add_field(name="📋 Crew Leadership", value=leadership, inline=False)

# 3. Walkers (divider before)
embed.add_field(name="​", value=f"{SEP}\n**Walkers:**\n{pills_paired(walkers)}", inline=False)

# 4. Trainees (divider before)
embed.add_field(name="​", value=f"{SEP}\n**Trainees:**\n{pills_paired(trainees)}", inline=False)

# Footer
embed.set_footer(text=f"{SEP}\nDispatch date: {dispatch_date}")
```

### Why Driver and Trainers Share One Field

Discord renders a blank line between embed field values and the next field name, creating unwanted whitespace if Driver and Trainers are separate fields. Combining them into one field with `\n\n` between driver and trainers produces the correct tight spacing.

---

## Bot Hot-Reload Behavior

**The Discord bot does NOT hot-reload.** This is the most critical operational note for future development.

| Service | Reload behavior |
|---|---|
| `backend` | uvicorn `--reload` — picks up file changes automatically |
| `bot` | Plain `python main.py` — **must be restarted to pick up any code change** |
| `celery_worker` | Plain celery process — **must be restarted for task changes** |

**Minimum action for bot code changes:**
```bash
docker compose restart bot
```

**Required when dependencies change (`requirements.txt`):**
```bash
docker compose up -d --build bot
```

**Full teardown (use when multiple services changed or state is uncertain):**
```bash
docker compose down && docker compose up -d --build
```

Symptoms of running stale bot code: edits to `bot/cogs/dispatch.py` have no effect on Discord output despite the file being correct on disk. Always restart after any bot code edit.

---

## Alternatives Rejected

- **Plain-text code block (`\`\`\`...`\`\`\`)**: Single field, monospace alignment works, but no blue left accent border and the block renders as a flat grey rectangle with no section hierarchy.
- **Multi-field inline grids (one field per name)**: Hits Discord's 25-field limit immediately with crews of 13+ walkers. Rejected.
- **Embed fields per section with inline=True columns**: Discord's 3-column inline layout is unpredictable — a missing third-column spacer causes sections to collapse onto the same row. Hard to maintain. Rejected.
- **No empty right pill for odd names**: Tried. The asymmetric row looks worse than a consistent empty box. Kept empty pill for visual grid regularity.

---

## Files Changed

- `bot/cogs/dispatch.py` — `_build_truck_channel_embed()` rewritten
