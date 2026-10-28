"""
apply_config.py
---------------
Run this script any time you update config.txt.
It regenerates all *_configured.ipynb notebooks (root + Partners folder)
with the latest config values.

Usage:
    python apply_config.py
"""

import json
import os
import sys

sys.stdout.reconfigure(encoding='utf-8')

UTIL_LINE = r'UTIL_PATH = F"D:\Officedata\Feature_Universe_Training"'
INSERT_AFTER = "schema3 = 'dap_ds_poweruser_playground'"

# Root-level notebooks: need UTIL_PATH injected (used for sys.path imports)
ROOT_NOTEBOOKS = [
    ('Part1_Applied_Trans_Table_configured.ipynb',  'Part1_Applied_Trans_Table_configured.ipynb'),
    ('Part2_DC_Steps_configured.ipynb',             'Part2_DC_Steps_configured.ipynb'),
    ('Part3_Partners_Steps_configured.ipynb',       'Part3_Partners_Steps_configured.ipynb'),
    ('Part3_Partners_Steps_configured.ipynb',          'Part4_Final_Steps_configured copy.ipynb'),
]

# Partners notebooks: plain config.txt content (no UTIL_PATH needed)
PARTNER_NOTEBOOKS = [
    ('Partners/cash_demo_feature_creation.ipynb',       'Partners/cash_demo_feature_creation_configured.ipynb'),
    ('Partners/cic_features_20260706.ipynb',            'Partners/cic_features_20260706_configured.ipynb'),
    ('Partners/cic_features_digit_loop_20260706.ipynb', 'Partners/cic_features_digit_loop_20260706_configured.ipynb'),
    ('Partners/device_score_android_feature_creation.ipynb', 'Partners/device_score_android_feature_creation_configured.ipynb'),
    ('Partners/ios_device_score_features.ipynb',        'Partners/ios_device_score_features_configured.ipynb'),
    ('Partners/model_app_features.ipynb',               'Partners/model_app_features_configured.ipynb'),
]


def read_config(config_path):
    with open(config_path, encoding='utf-8') as f:
        return f.read().strip()


def build_config_with_util(config_text):
    """Inject UTIL_PATH after schema3 line (required by root notebooks for sys.path)."""
    lines = config_text.splitlines()
    new_lines = []
    for line in lines:
        new_lines.append(line)
        if line.strip() == INSERT_AFTER:
            new_lines.append('')
            new_lines.append(UTIL_LINE)
    return '\n'.join(new_lines)


def apply_to_notebook(src_path, dst_path, new_config_source):
    with open(src_path, encoding='utf-8') as f:
        nb = json.load(f)

    config_cell_idx = None
    for i, cell in enumerate(nb['cells']):
        if cell['cell_type'] == 'code' and '# B Score model configuration' in ''.join(cell['source']):
            config_cell_idx = i
            break

    if config_cell_idx is None:
        print(f"  WARNING: config cell not found in {src_path} — skipped.")
        return

    # Write source as a line list (standard Jupyter format)
    split_lines = new_config_source.splitlines(keepends=False)
    new_source_list = [line + '\n' for line in split_lines[:-1]] + [split_lines[-1]]
    nb['cells'][config_cell_idx]['source'] = new_source_list

    # Clear stale outputs
    nb['cells'][config_cell_idx]['outputs'] = []
    nb['cells'][config_cell_idx]['execution_count'] = None

    with open(dst_path, 'w', encoding='utf-8') as f:
        json.dump(nb, f, ensure_ascii=False, indent=1)

    print(f"  Created: {dst_path}")


if __name__ == '__main__':
    script_dir = os.path.dirname(os.path.abspath(__file__))
    config_path = os.path.join(script_dir, 'config.txt')

    if not os.path.exists(config_path):
        print(f"ERROR: config.txt not found at {config_path}")
        sys.exit(1)

    print(f"Reading config from: {config_path}\n")
    raw_config   = read_config(config_path)
    config_with_util = build_config_with_util(raw_config)

    print("--- Root notebooks ---")
    for src_name, dst_name in ROOT_NOTEBOOKS:
        src_path = os.path.join(script_dir, src_name)
        dst_path = os.path.join(script_dir, dst_name)
        if not os.path.exists(src_path):
            print(f"  WARNING: not found: {src_name} — skipped.")
            continue
        apply_to_notebook(src_path, dst_path, config_with_util)

    print("\n--- Partners notebooks ---")
    for src_name, dst_name in PARTNER_NOTEBOOKS:
        src_path = os.path.join(script_dir, src_name)
        dst_path = os.path.join(script_dir, dst_name)
        if not os.path.exists(src_path):
            print(f"  WARNING: not found: {src_name} — skipped.")
            continue
        apply_to_notebook(src_path, dst_path, raw_config)

    print("\nDone. All configured notebooks are up to date.")
