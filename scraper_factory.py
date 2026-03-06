"""
scraper_factory.py - Factory pattern để chọn scraper
"""

import json
from pathlib import Path


def load_config():
    """Load config.json"""
    config_path = Path("config.json")
    if config_path.exists():
        with open(config_path, 'r', encoding='utf-8') as f:
            return json.load(f)
    return {
        "tax-gov": "https://tracuunnt.gdt.gov.vn/tcnnt/mstcn.jsp",
        "tax-3rd": "https://masothue.com"
    }


def get_scraper(source="tax-3rd", headless=False, parallel=None, progress_callback=None):
    """
    Factory function để tạo scraper phù hợp
    
    Args:
        source: "tax-gov" hoặc "tax-3rd"
        headless: True/False
        parallel: None (auto từ config), True (force parallel), False (force single), hoặc số workers
        progress_callback: Callback function(current, total, result) để update progress
        
    Returns:
        Scraper instance
    """
    if source == "tax-gov":
        # Tax-gov: Hỗ trợ parallel
        if parallel and isinstance(parallel, int) and parallel > 1:
            # Parallel mode với số workers chỉ định
            from scraper_gov_parallel import ParallelTaxGovScraper
            return ParallelTaxGovScraper(num_workers=parallel, headless=headless, progress_callback=progress_callback)
        elif parallel is True:
            # Parallel mode với default 3 workers
            from scraper_gov_parallel import ParallelTaxGovScraper
            return ParallelTaxGovScraper(num_workers=3, headless=headless, progress_callback=progress_callback)
        else:
            # Single mode
            from scraper_gov import TaxGovScraper
            return TaxGovScraper(headless=headless)
            
    elif source == "tax-3rd":
        # Kiểm tra parallel mode
        config = load_config()
        parallel_config = config.get("parallel", {})
        
        # Xác định có dùng parallel hay không
        use_parallel = False
        num_workers = 5
        
        if parallel is None:
            # Auto từ config
            use_parallel = parallel_config.get("enabled", False)
            num_workers = parallel_config.get("num_workers", 5)
        elif parallel is True:
            # Force parallel với config
            use_parallel = True
            num_workers = parallel_config.get("num_workers", 5)
        elif parallel is False:
            # Force single
            use_parallel = False
        elif isinstance(parallel, int):
            # Chỉ định số workers
            use_parallel = True
            num_workers = parallel
        
        if use_parallel:
            from scraper_parallel import ParallelTaxScraper
            return ParallelTaxScraper(num_workers=num_workers, headless=headless)
        else:
            from scraper_selenium import TaxScraper
            return TaxScraper(headless=headless)
    else:
        raise ValueError(f"Unknown source: {source}. Use 'tax-gov' or 'tax-3rd'")


def get_source_info():
    """Lấy thông tin về các nguồn tra cứu"""
    config = load_config()
    return {
        "tax-gov": {
            "name": "Cục Thuế (Chính phủ)",
            "url": config.get("tax-gov", ""),
            "features": ["Chính thức", "Có CAPTCHA", "Chậm hơn"],
            "supports": ["MST 10 số"]
        },
        "tax-3rd": {
            "name": "MaSoThue.com (Bên thứ 3)",
            "url": config.get("tax-3rd", ""),
            "features": ["Nhanh", "Không CAPTCHA", "Nhiều thông tin hơn"],
            "supports": ["MST 10 số", "CCCD 12 số"]
        }
    }


if __name__ == "__main__":
    # Test
    info = get_source_info()
    for key, val in info.items():
        print(f"\n{key}:")
        print(f"  Name: {val['name']}")
        print(f"  URL: {val['url']}")
        print(f"  Features: {', '.join(val['features'])}")
        print(f"  Supports: {', '.join(val['supports'])}")
