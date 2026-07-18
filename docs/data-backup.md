# Data Backup & Secondary Machine

How to replicate the untracked backtest data (`data/`) to the secondary
workstation so backtests can run there. The code travels through git; the ~5.8 GB
of historical parquet does not (it is untracked and never committed — see
CLAUDE.md), so it must be copied out of band.

## Secondary machine

- Host: `mihai@192.168.1.111` (hostname `mihai-Latitude-5401`)
- Repo path: `~/workspace/meridian/`
- SSH: key-based (local `id_ed25519`), port 22. If a connect attempt is
  refused, the box is usually just booting / off Wi-Fi — retry, don't assume a
  config problem.

## What lives in `data/` (all untracked)

- `historical/` — one **combined, split-adjusted** parquet per symbol spanning
  the full range, e.g. `AAPL_1m_2024-08-01_2026-02-01.parquet` (1445 files,
  ~5.5 GB, S&P 1500). `historical/manifest.json` records coverage per file.
- `fulltest_results/` — fulltest and OOS reports (JSON + text).
- `momentum/`, `diagnostics/` — smaller run artifacts.

### Layout note (important)

The current layout is **one file per symbol for the whole 2024-08-01 → 2026-02-01
range**. An earlier layout used **two files per symbol** split at 2025-08-01
(`..._2024-08-01_2025-08-01.parquet` + `..._2025-08-01_2026-02-01.parquet`) and
was not split-adjusted. If a machine ever ends up with **both** schemes, the
fulltest loader can pick up the stale unadjusted files — always mirror (below),
never merge the two layouts.

## Backing up data → secondary (mirror)

Scoped to `data/` only. Does **not** touch git or any untracked non-data files
(e.g. `TODO.md`, `docs/iterations/*-plan.md`) on the remote.

```bash
rsync -avh --delete --info=progress2 \
  /home/mihai/workspace/meridian/data/ \
  mihai@192.168.1.111:~/workspace/meridian/data/
```

- `--delete` makes it an exact mirror, removing any old-layout parquet on the
  remote. This is the whole point — see the layout note above.
- Verify with a dry run afterwards; zero pending changes means an exact match:
  ```bash
  rsync -avhn --delete \
    /home/mihai/workspace/meridian/data/ \
    mihai@192.168.1.111:~/workspace/meridian/data/ | grep -Ec 'parquet|deleting'
  # 0 == in sync
  ```
- ~5.8 GB over LAN takes a few minutes (~20 MB/s observed).

The data is regenerable if a backup is ever lost:
`python -m axtrade.fulltest download --start 2024-08-01 --end 2026-02-01 --universe sp1500`.

## Keep code in sync too

Data alone is not enough — the phase-5 code expects the split-adjusted data.
The secondary repo tracks `main` but can lag, and local `main` may hold
commits not yet on GitHub. Before running backtests on the secondary:

```bash
# on the primary
git push origin main
# on the secondary
cd ~/workspace/meridian && git pull
```
