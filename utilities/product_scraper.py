#!/usr/bin/env python3
import os, sys, json, re, datetime
from urllib.parse import urlencode
import requests
from bs4 import BeautifulSoup
from dotenv import load_dotenv
from urllib.parse import urlparse



API_BASE = "https://api.zenrows.com/v1/"

PRICE_RE = re.compile(
    r"(?P<currency>[\$€£¥]|USD|EUR|GBP|JPY|AUD|CAD|CHF|CNY|INR|MXN|R\$|kr|zł|₩|₽)?\s*"
    r"(?P<amount>\d{1,3}(?:[,\s]\d{3})*(?:\.\d{2})?|\d+(?:\.\d{2})?)",
    re.IGNORECASE,
)
load_dotenv()
ZENROWS_API_KEY = os.getenv('ZENROWS_API_KEY')
ZENROWS_RENDER_JS = os.getenv('ZENROWS_RENDER_JS','false').lower() in ('1','true','yes')
ZENROWS_PREMIUM = os.getenv('ZENROWS_PREMIUM','false').lower() in ('1','true','yes')
ZENROWS_LOCATION = os.getenv('ZENROWS_LOCATION')  # optional

class ProductScraper:
    def __init__(self, api_key):
        self.api_key = api_key
        self.api_base = "https://api.zenrows.com/v1/"

    @staticmethod
    def _read_url_from_cli_or_stdin():
        if len(sys.argv) > 1:
            return sys.argv[1].strip()
        data = sys.stdin.read().strip()
        if not data:
            sys.stderr.write("Usage: python get_product.py <url>  OR  echo <url> | python get_product.py\n")
            sys.exit(2)
        return data.splitlines()[0].strip()

    def _fetch_html_via_zenrows(self, url: str, apikey: str) -> str:
        params = {
            "apikey": apikey,
            "url": url,
            "js_render": "true",        # render JS so modern stores work
            "premium_proxy": "true",    # better chance past bot-walls
            "antibot": "true",
            # "wait_until": "networkidle",  # uncomment if needed
        }
        r = requests.get(API_BASE, params=params, timeout=60)
        r.raise_for_status()
        return r.text

    def _try_jsonld_product(self,soup: BeautifulSoup):
        for tag in soup.find_all("script", attrs={"type": "application/ld+json"}):
            try:
                # Some sites include multiple JSON objects in one script or malformed JSON
                data = json.loads(tag.string or tag.text or "{}")
            except Exception:
                continue

            candidates = data if isinstance(data, list) else [data]
            for obj in candidates:
                # Handle @graph
                if isinstance(obj, dict) and "@graph" in obj and isinstance(obj["@graph"], list):
                    candidates.extend(obj["@graph"])
                    continue

                if not isinstance(obj, dict):
                    continue
                typ = obj.get("@type") or obj.get("@type".lower())
                if isinstance(typ, list):
                    is_product = any(t.lower() == "product" for t in typ if isinstance(t, str))
                else:
                    is_product = isinstance(typ, str) and typ.lower() == "product"
                if not is_product:
                    continue

                name = (obj.get("name") or "").strip() or None
                price = currency = None
                offers = obj.get("offers")
                if isinstance(offers, dict):
                    price = offers.get("price") or offers.get("lowPrice") or offers.get("highPrice")
                    currency = offers.get("priceCurrency")
                elif isinstance(offers, list) and offers:
                    first = offers[0]
                    if isinstance(first, dict):
                        price = first.get("price") or first.get("lowPrice") or first.get("highPrice")
                        currency = first.get("priceCurrency")
                if name and price:
                    return {"name": name, "price": str(price), "currency": (currency or "").upper() or None, "source": "jsonld"}
        return None

    def _meta_content(self,soup, *selectors):
        for sel in selectors:
            tag = soup.select_one(sel)
            if tag:
                # meta content vs element text
                if tag.has_attr("content"):
                    return tag["content"].strip()
                txt = tag.get_text(" ", strip=True)
                if txt:
                    return txt
        return None

    def _try_meta_tags(self,soup: BeautifulSoup):
        name = self._meta_content(
            soup,
            'meta[property="og:title"]',
            'meta[name="og:title"]',
            'meta[name="twitter:title"]',
            "title",
            "h1",
        )
        # Many stores expose price in itemprop or meta
        price = self._meta_content(
            soup,
            'meta[itemprop="price"]',
            'meta[property="product:price:amount"]',
            '[data-price]',
            '[data-product-price]',
            '[itemprop="price"]',
        )
        currency = self._meta_content(
            soup,
            'meta[itemprop="priceCurrency"]',
            'meta[property="product:price:currency"]',
            '[itemprop="priceCurrency"]',
        )
        if name and (price or currency):
            return {"name": name, "price": price, "currency": currency, "source": "meta"}
        return None

    def _try_dom_price_guess(self,soup: BeautifulSoup):
        # Look for common price classes/ids
        candidates = soup.select(
            """
            [class*="price"], [id*="price"], [class*="amount"], [id*="amount"],
            span.price, div.price, p.price, .product-price, .sales, .current-price
            """
        )
        best_hit = None
        for el in candidates[:200]:
            txt = el.get_text(" ", strip=True)
            if not txt:
                continue
            m = PRICE_RE.search(txt)
            if m:
                best_hit = (txt, m)
                break
        if best_hit:
            txt, m = best_hit
            amount = m.group("amount")
            curr = m.group("currency")
            return {"raw_price_text": txt, "price": amount, "currency": (curr or "").upper() or None, "source": "regex-dom"}
        return None

    def _get_domain(self,url):
        domain = urlparse(url).netloc
        return domain.lower() if domain else None

    def _normalize_price(self,p):
        if p is None:
            return None
        # strip thousands separators like "1,299.00" or "1 299,00"
        p = str(p).strip()
        p = p.replace("\u00A0", " ").replace(" ", "")
        # If both comma and dot appear, assume comma is thousand sep (en-US style)
        if "," in p and "." in p:
            p = p.replace(",", "")
        # If only comma and no dot, likely decimal comma -> convert to dot
        elif "," in p and "." not in p:
            p = p.replace(",", ".")
        # remove any stray non-numeric except dot/minus
        p = re.sub(r"[^0-9.\-]", "", p)
        return p or None

    def scrape(self, url: str):

        apikey = ZENROWS_API_KEY
        if not apikey:
            sys.stderr.write("Set ZENROWS_API_KEY in your environment.\n")
        result = url if url and url is not None else ProductScraper._read_url_from_cli_or_stdin()
        url = result
        html = self._fetch_html_via_zenrows(url, apikey)
        soup = BeautifulSoup(html, "lxml")

        result = self._try_jsonld_product(soup) or self._try_meta_tags(soup) or self._try_dom_price_guess(soup)

        if result:
            # Try to fill gaps between strategies
            if not result.get("name"):
                result["name"] = self._meta_content(soup, 'meta[property="og:title"]', "h1", "title")

            result["price"] = self._normalize_price(result.get("price"))
            out = {
                "url": url,
                "name": result.get("name"),
                "price": result.get("price"),
                "currency": result.get("currency"),
                "source": result.get("source"),
                "domain": self._get_domain(url),
                "timestamp": datetime.datetime.now(datetime.UTC).isoformat(),
            }
            # include raw text if we got it via regex
            if "raw_price_text" in result:
                out["raw_price_text"] = result["raw_price_text"]
            print(json.dumps(out, ensure_ascii=False))
            return out

        # Nothing found – keep a small debug sample to help troubleshoot
        snippet = BeautifulSoup(html[:2000], "lxml").get_text(" ", strip=True)[:300]
        sys.stderr.write("Could not extract product name/price. First 300 chars of page text:\n" + snippet + "\n")

