"""
Google Sheets Product Auto-Fill Script
Optimized for Amazon, Home Depot, and Rockler

Requirements:
pip install gspread google-auth requests beautifulsoup4 lxml
"""

import gspread
from google.oauth2.service_account import Credentials
import requests
from bs4 import BeautifulSoup
import re
import time

# Google Sheets Setup
SCOPES = [
    'https://www.googleapis.com/auth/spreadsheets',
    'https://www.googleapis.com/auth/drive'
]

# Configuration
CREDENTIALS_FILE = 'credentials.json'  # Path to your Google service account JSON
SHEET_NAME = 'The Absurd List of Absurd Shop Things'  # Change this to your sheet name
WORKSHEET_NAME = 'Accserories'  # Change if different

# Column Configuration (can use letter like 'A' or number like 1)
URL_COLUMN = 'E'  # Column containing product URLs
NAME_COLUMN = 'B'  # Column where product names will be written
PRICE_COLUMN = 'D'  # Column where prices will be written

# Headers to mimic a browser
HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
    'Accept-Language': 'en-US,en;q=0.5',
    'Accept-Encoding': 'gzip, deflate, br',
    'Connection': 'keep-alive',
}


def get_google_sheet():
    """Connect to Google Sheets and return the worksheet"""
    creds = Credentials.from_service_account_file(CREDENTIALS_FILE, scopes=SCOPES)
    client = gspread.authorize(creds)
    spreadsheet = client.open(SHEET_NAME)
    worksheet = spreadsheet.worksheet(WORKSHEET_NAME)
    return worksheet


def column_to_index(col):
    """Convert column letter to index (A=0, B=1, etc.) or return number-1 if number given"""
    if isinstance(col, int):
        return col - 1
    elif isinstance(col, str):
        if col.isdigit():
            return int(col) - 1
        # Convert letter to index (A=0, B=1, etc.)
        col = col.upper()
        result = 0
        for char in col:
            result = result * 26 + (ord(char) - ord('A') + 1)
        return result - 1
    return 0


def index_to_letter(index):
    """Convert column index to letter (0=A, 1=B, etc.)"""
    letter = ''
    index += 1  # Convert to 1-based
    while index > 0:
        index -= 1
        letter = chr(index % 26 + ord('A')) + letter
        index //= 26
    return letter


def fetch_page(url):
    """Fetch webpage content"""
    try:
        response = requests.get(url, headers=HEADERS, timeout=10)
        response.raise_for_status()
        return response.text
    except Exception as e:
        print(f"Error fetching {url}: {e}")
        return None


def clean_text(text):
    """Clean extracted text"""
    if not text:
        return None
    text = text.strip()
    text = re.sub(r'\s+', ' ', text)
    return text


def get_domain(url):
    """Extract domain from URL"""
    match = re.search(r'https?://([^/]+)', url, re.IGNORECASE)
    return match.group(1).lower() if match else ''


# ===== AMAZON EXTRACTORS =====
def extract_amazon_name(soup):
    """Extract product name from Amazon"""
    # Try product title
    title = soup.find('span', {'id': 'productTitle'})
    if title:
        return clean_text(title.get_text())
    
    # Try title tag
    title = soup.find('title')
    if title:
        text = clean_text(title.get_text())
        text = re.sub(r'^Amazon\.com\s*:\s*', '', text, flags=re.IGNORECASE)
        return text
    
    return None


def extract_amazon_price(soup):
    """Extract price from Amazon"""
    # Try whole price
    price_whole = soup.find('span', class_='a-price-whole')
    price_fraction = soup.find('span', class_='a-price-fraction')
    if price_whole:
        whole = price_whole.get_text().replace(',', '').replace('.', '')
        fraction = price_fraction.get_text() if price_fraction else '00'
        return f"${whole}.{fraction}"
    
    # Try offscreen price
    price = soup.find('span', class_='a-offscreen')
    if price:
        price_text = price.get_text()
        match = re.search(r'\$?([0-9,.]+)', price_text)
        if match:
            return f"${match.group(1).replace(',', '')}"
    
    return None


# ===== HOME DEPOT EXTRACTORS =====
def extract_homedepot_name(soup):
    """Extract product name from Home Depot"""
    # Try h1 with product title
    title = soup.find('h1', class_=re.compile('product.*title', re.IGNORECASE))
    if title:
        return clean_text(title.get_text())
    
    # Try any h1
    title = soup.find('h1')
    if title:
        return clean_text(title.get_text())
    
    # Try meta tag
    meta = soup.find('meta', property='og:title')
    if meta and meta.get('content'):
        return clean_text(meta['content'])
    
    return None


def extract_homedepot_price(soup):
    """Extract price from Home Depot"""
    # Try price span
    price = soup.find('span', class_=re.compile('price', re.IGNORECASE))
    if price:
        price_text = price.get_text()
        match = re.search(r'\$?([0-9,.]+)', price_text)
        if match:
            return f"${match.group(1).replace(',', '')}"
    
    # Try structured data
    script = soup.find('script', type='application/ld+json')
    if script:
        match = re.search(r'"price"\s*:\s*"?([0-9,.]+)"?', script.string or '')
        if match:
            return f"${match.group(1).replace(',', '')}"
    
    return None


# ===== ROCKLER EXTRACTORS =====
def extract_rockler_name(soup):
    """Extract product name from Rockler"""
    # Try product name h1
    title = soup.find('h1', class_=re.compile('product.*name', re.IGNORECASE))
    if title:
        return clean_text(title.get_text())
    
    # Try any h1
    title = soup.find('h1')
    if title:
        return clean_text(title.get_text())
    
    # Try meta tag
    meta = soup.find('meta', property='og:title')
    if meta and meta.get('content'):
        return clean_text(meta['content'])
    
    return None


def extract_rockler_price(soup):
    """Extract price from Rockler"""
    # Try price span
    price = soup.find('span', class_=re.compile('price', re.IGNORECASE))
    if price:
        price_text = price.get_text()
        match = re.search(r'\$?([0-9,.]+)', price_text)
        if match:
            return f"${match.group(1).replace(',', '')}"
    
    # Try any price pattern in HTML
    html_text = str(soup)
    match = re.search(r'"price"\s*:\s*"?([0-9,.]+)"?', html_text)
    if match:
        return f"${match.group(1).replace(',', '')}"
    
    return None


def extract_product_info(url):
    """Extract product name and price from URL"""
    html = fetch_page(url)
    if not html:
        return None, None
    
    soup = BeautifulSoup(html, 'lxml')
    domain = get_domain(url)
    
    name = None
    price = None
    
    if 'amazon' in domain:
        print(f"  Extracting from Amazon...")
        name = extract_amazon_name(soup)
        price = extract_amazon_price(soup)
    elif 'homedepot' in domain:
        print(f"  Extracting from Home Depot...")
        name = extract_homedepot_name(soup)
        price = extract_homedepot_price(soup)
    elif 'rockler' in domain:
        print(f"  Extracting from Rockler...")
        name = extract_rockler_name(soup)
        price = extract_rockler_price(soup)
    else:
        print(f"  Unknown site, using generic extraction...")
        # Generic extraction
        meta = soup.find('meta', property='og:title')
        if meta and meta.get('content'):
            name = clean_text(meta['content'])
        elif soup.find('title'):
            name = clean_text(soup.find('title').get_text())
        
        # Generic price search
        html_text = str(soup)
        match = re.search(r'\$([0-9]{1,3}(?:,?[0-9]{3})*(?:\.[0-9]{2})?)', html_text)
        if match:
            price = f"${match.group(1).replace(',', '')}"
    
    return name, price


def main():
    """Main function to process Google Sheet"""
    print("Connecting to Google Sheets...")
    worksheet = get_google_sheet()
    
    # Convert column identifiers to indices
    url_col_idx = column_to_index(URL_COLUMN)
    name_col_idx = column_to_index(NAME_COLUMN)
    price_col_idx = column_to_index(PRICE_COLUMN)
    
    name_col_letter = index_to_letter(name_col_idx)
    price_col_letter = index_to_letter(price_col_idx)
    
    print(f"Configuration:")
    print(f"  URL Column: {URL_COLUMN} (index {url_col_idx})")
    print(f"  Name Column: {NAME_COLUMN} (index {name_col_idx})")
    print(f"  Price Column: {PRICE_COLUMN} (index {price_col_idx})")
    
    # Get all values
    print("\nFetching sheet data...")
    all_values = worksheet.get_all_values()
    
    if len(all_values) < 2:
        print("Sheet is empty or has no data rows")
        return
    
    # Process each row (skip header)
    updates = []
    for i, row in enumerate(all_values[1:], start=2):  # Start from row 2
        if not row or len(row) <= url_col_idx:  # Skip empty rows or rows without URL column
            continue
        
        url = row[url_col_idx] if len(row) > url_col_idx else ''
        
        # Check if URL is valid and columns B and C are empty or need update
        if url and (url.startswith('http://') or url.startswith('https://')):
            print(f"\nProcessing row {i}: {url[:60]}...")
            
            name, price = extract_product_info(url)
            
            if name:
                print(f"  ✓ Name: {name[:60]}...")
                updates.append({
                    'range': f'{name_col_letter}{i}',
                    'values': [[name]]
                })
            else:
                print(f"  ✗ Name not found")
                updates.append({
                    'range': f'{name_col_letter}{i}',
                    'values': [['Name not found']]
                })
            
            if price:
                print(f"  ✓ Price: {price}")
                updates.append({
                    'range': f'{price_col_letter}{i}',
                    'values': [[price]]
                })
            else:
                print(f"  ✗ Price not found")
                updates.append({
                    'range': f'{price_col_letter}{i}',
                    'values': [['Price not found']]
                })
            
            # Be nice to the servers - delay between requests
            time.sleep(2)
    
    # Batch update all changes
    if updates:
        print(f"\nUpdating {len(updates)} cells in Google Sheets...")
        worksheet.batch_update(updates)
        print("✓ All updates complete!")
    else:
        print("\nNo URLs found to process.")


if __name__ == '__main__':
    main()