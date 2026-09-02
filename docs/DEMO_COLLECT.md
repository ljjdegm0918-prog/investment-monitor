# DEMO_COLLECT — 7 天采集烟测

在项目根目录、已 `pip install -e .` 且 venv 有 pytest/tzdata 时：

```powershell
Set-Location "C:\path\to\investment-monitor"
$env:PYTHONPATH="src"
$start = (Get-Date).AddDays(-7).ToString("yyyy-MM-dd")
$end = (Get-Date).ToString("yyyy-MM-dd")
```

## 1. UK · VOD · 新闻

```powershell
python -c "
from datetime import date
from investment_monitor.registry import create_default_registry
from investment_monitor.models import CollectionRequest
r=create_default_registry()
c=[x for x in r.load_enabled(['yahoo_uk','google_news_uk'])][0]
req=CollectionRequest(tickers=['VOD'], start_date=date.fromisoformat('$start'), end_date=date.fromisoformat('$end'), markets={'VOD':'uk'})
print(c.name, len(c.collect(req)))
"
```

预期：≥0 行；网络失败则 connector last_errors 诚实非空。

## 2. JP · 7203 · 新闻

```powershell
python -c "
from datetime import date
from investment_monitor.registry import create_default_registry
from investment_monitor.models import CollectionRequest
r=create_default_registry()
for name in ['yahoo_jp','google_news_jp']:
    c=r.factory_for(name)()
    n=len(c.collect(CollectionRequest(tickers=['7203'], start_date=date.fromisoformat('$start'), end_date=date.fromisoformat('$end'), markets={'7203':'jp'})))
    print(name, n)
"
```

## 3. AU · BHP · 披露 + 新闻

```powershell
python -c "
from datetime import date
from investment_monitor.registry import create_default_registry
from investment_monitor.models import CollectionRequest
r=create_default_registry()
req=CollectionRequest(tickers=['BHP'], start_date=date.fromisoformat('$start'), end_date=date.fromisoformat('$end'), markets={'BHP':'au'})
for name in ['asx_announcements','yahoo_au','google_news_au','stockhead_au']:
    c=r.factory_for(name)()
    items=c.collect(req)
    print(name, len(items), (items[0].raw_metadata or {}).get('api_max_items_per_company') if name=='asx_announcements' and items else '')
"
```

预期：ASX ≤5 条/次；stockhead 为 community 类型。
