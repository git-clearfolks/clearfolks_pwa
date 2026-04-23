#!/usr/bin/env python3
"""
QA Agent — checks all published PWAs for broken onclick handlers.
Reports missing functions, incomplete HTML, and common issues.
"""

import os
import json
import re
from pathlib import Path

PRODUCTS_FILE = "/root/clearfolks/products.json"
WWW_ROOT = "/var/www/clearfolk"

def qa_check(slug, name):
    path = f"{WWW_ROOT}/{slug}/index.html"
    issues = []
    
    if not os.path.exists(path):
        return [f"CRITICAL: index.html missing at {path}"]

    with open(path) as f:
        html = f.read()

    # Check HTML is complete
    if not html.strip().endswith("</html>"):
        issues.append("CRITICAL: HTML file is incomplete — missing </html>")

    # Check </body> exists
    if "</body>" not in html:
        issues.append("CRITICAL: Missing </body> tag — JS likely cut off")

    # Check <script> tag exists
    if "<script>" not in html and "<script " not in html:
        issues.append("CRITICAL: No <script> tag found — no JavaScript")

    # Extract all onclick functions called
    onclick_calls = re.findall(r"onclick=[\"'](?!if|for|while|switch)(\w+)\(", html)
    onclick_functions = set(onclick_calls)

    # Extract all defined functions
    defined_functions = set(re.findall(r"function (\w+)\s*\(", html))

    # Check each onclick function is defined
    missing = onclick_functions - defined_functions
    for fn in sorted(missing):
        issues.append(f"MISSING FUNCTION: {fn}() is called but never defined")

    # Check switchSection or equivalent nav function exists
    if "switchSection" in html and "function switchSection" not in html:
        issues.append("MISSING FUNCTION: switchSection() — navigation will be broken")

    # Check localStorage usage
    if "localStorage" not in html:
        issues.append("WARNING: No localStorage usage — data won't persist")

    # Check service worker
    if "serviceWorker" not in html:
        issues.append("WARNING: No service worker registration")

    # Check brand footer
    if "clearfolks.com" not in html:
        issues.append("WARNING: Missing brand footer")

    # Check manifest
    if "manifest.json" not in html:
        issues.append("WARNING: Missing manifest link")

    return issues

def main():
    if not os.path.exists(PRODUCTS_FILE):
        print("ERROR: products.json not found")
        return

    with open(PRODUCTS_FILE) as f:
        data = json.load(f)

    products = data.get("products", [])
    print(f"QA checking {len(products)} products...\n")

    all_clear = True
    results = []

    for p in products:
        name = p["name"]
        slug = p["slug"]
        url = p["url"]
        issues = qa_check(slug, name)

        status = "PASS" if not issues else "FAIL"
        if issues:
            all_clear = False

        results.append({
            "id": p["id"],
            "name": name,
            "slug": slug,
            "url": url,
            "status": status,
            "issues": issues
        })

        print(f"[{status}] {p['id']} — {name}")
        print(f"  URL: {url}")
        if issues:
            for issue in issues:
                prefix = "  !! " if "CRITICAL" in issue else "  >> "
                print(f"{prefix}{issue}")
        print()

    print("=" * 60)
    passed = len([r for r in results if r["status"] == "PASS"])
    failed = len([r for r in results if r["status"] == "FAIL"])
    print(f"Results: {passed} passed, {failed} failed")

    if all_clear:
        print("All products passed QA.")
    else:
        print("\nFix CRITICAL issues before listing on Etsy.")

    # Save QA report
    report_path = "/root/clearfolks/logs/qa-report.json"
    with open(report_path, "w") as f:
        json.dump(results, f, indent=2)
    print(f"\nReport saved: {report_path}")

if __name__ == "__main__":
    main()
