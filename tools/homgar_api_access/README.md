# HomGar API Access Helper

This folder contains a standalone script for testing login against the HomGar API and discovering the correct `area_code`.

In this API, `area_code` appears to be the phone country code associated with the account, not a local city/area prefix. Common examples:

- `1` = US / Canada
- `31` = Netherlands
- `33` = France

This backend also appears to distinguish between branded apps using `appCode`:

- `1` = HomGar
- `2` = RainPoint
- `4` = RainPoint Agri

## What the script does

- Tests a specific `area_code`, or several in sequence
- Tests one or more `appCode` values as well
- Verifies login by calling the homes endpoint
- Prints the first working `appCode` + `area_code` combination
- Optionally writes a JSON auth cache you can reuse in other scripts

## Requirements

- Python 3
- `requests`

Install `requests` if needed:

```powershell
python -m pip install requests
```

## Usage

Try the built-in short list of likely values:

```powershell
python .\tools\homgar_api_access\homgar_api_access.py --email you@example.com --common
```

Try specific area codes in your own order:

```powershell
python .\tools\homgar_api_access\homgar_api_access.py --email you@example.com --area-codes 1,33,31
```

Try both HomGar and RainPoint:

```powershell
python .\tools\homgar_api_access\homgar_api_access.py --email you@example.com --app-codes 1,2 --area-codes 1,33,31
```

Try one exact code:

```powershell
python .\tools\homgar_api_access\homgar_api_access.py --email you@example.com --app-code 2 --area-code 1
```

Save the successful auth response:

```powershell
python .\tools\homgar_api_access\homgar_api_access.py --email you@example.com --app-codes 1,2 --area-codes 1,33,31 --save-auth .\tools\homgar_api_access\auth_cache.json
```

If you do not pass `--password`, the script prompts for it securely.

## Rate limiting

If the API replies with `operate too frequently`, it is throttling login attempts. The script now waits 60 seconds and retries the same code before moving on.

You can increase the cooldown if needed:

```powershell
python .\tools\homgar_api_access\homgar_api_access.py --email you@example.com --area-codes 1,33,31 --rate-limit-wait 120
```
