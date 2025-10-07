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
import os
import json
from dotenv import load_dotenv

import utilities.product_scraper as product_scraper

# Google Sheets Setup
SCOPES = [
    'https://www.googleapis.com/auth/spreadsheets',
    'https://www.googleapis.com/auth/drive'
]
load_dotenv()
# Access the environment variables
CREDENTIALS_FILE = os.getenv('CREDENTIALS_FILE','credentials.json')
SHEET_NAME = os.getenv('SHEET_NAME','The Absurd List of Absurd Shop Things')
WORKSHEET_NAME = os.getenv('WORKSHEET_NAME','Accserories') # Provide a default value
# Access the environment variables
URL_COLUMN = os.getenv('URL_COLUMN','E')
NAME_COLUMN = os.getenv('NAME_COLUMN','B')
PRICE_COLUMN = os.getenv('PRICE_COLUMN','D') # Provide a default value

# Headers to mimic a browser
HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
    'Accept-Language': 'en-US,en;q=0.5',
    'Accept-Encoding': 'gzip, deflate, br',
    'Connection': 'keep-alive',
}

PRODUCT_SCRAPER_INSTANCE=product_scraper.ProductScraper(os.getenv('ZENROWS_API_KEY'))

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

def get_domain(url):
    """Extract domain from URL"""
    match = re.search(r'https?://([^/]+)', url, re.IGNORECASE)
    return match.group(1).lower() if match else ''

def get_full_url(short_url: str) -> str | None:
    try:
        response = requests.get(short_url, allow_redirects=True, timeout=5)
        # Check if the request was successful and a redirect occurred
        if response.status_code == 200 and response.url != short_url:
            return response.url
        elif response.status_code == 200: # No redirect, original URL is the final URL
            return short_url
        else:
            print(f"Error: Request failed with status code {response.status_code}")
            return None
    except requests.exceptions.RequestException as e:
        print(f"Error during request: {e}")
        return None

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
        full_url = get_full_url(url)

        if full_url:
            print(f"Original shortened URL: {url}")
            print(f"Full URL: {full_url}")
            url = full_url
        
        # Check if URL is valid and columns B and C are empty or need update
        if url and (url.startswith('http://') or url.startswith('https://')):
            print(f"\nProcessing row {i}: {url[:60]}...")
            
            scrape_results = PRODUCT_SCRAPER_INSTANCE.scrape(url)
            name,domain,price = None,None,None
            if scrape_results:
                name = scrape_results.get("name")
                price = scrape_results.get("price")
                domain = scrape_results.get("domain")
                url = scrape_results.get("url",url)  # Update URL if scraper provides a final URL
            else:
                name = None
                price = None
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