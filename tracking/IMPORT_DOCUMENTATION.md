# Car Import Documentation

## Overview
The car import system has been updated to handle existing records by either updating them or skipping them, instead of just creating new records.

## Usage Options

### Default Behavior (Update Existing Records)
```bash
python manage.py import_cars --dry-run --max-rows 10
python manage.py import_cars
```
- **Default**: Updates existing records with new data from Excel
- Creates new records if they don't exist
- Uses `rego` (registration number) as the unique identifier

### Skip Existing Records
```bash
python manage.py import_cars --skip-existing --dry-run --max-rows 10
python manage.py import_cars --skip-existing
```
- Skips records that already exist in the database
- Only creates new records

## Command Line Options

| Option | Description | Default |
|--------|-------------|---------|
| `--file` | Path to Excel file | `tracking/CARS 22-11- 2024.xlsx` |
| `--dry-run` | Test run without saving data | `False` |
| `--max-rows` | Limit number of rows to process | `None` (all rows) |
| `--max-columns` | Limit number of columns to read | `25` |
| `--skip-existing` | Skip existing records instead of updating | `False` |

## Examples

### 1. Test Import with Dry Run
```bash
python manage.py import_cars --dry-run --max-rows 5
```

### 2. Import All Data (Update Existing)
```bash
python manage.py import_cars
```

### 3. Import New Records Only
```bash
python manage.py import_cars --skip-existing
```

### 4. Import from Custom File
```bash
python manage.py import_cars --file "path/to/custom_file.xlsx" --max-rows 50
```

## Output Examples

### Update Mode (Default)
```
✓ Created: ABC123 - Toyota Hilux Ute
↻ Updated: DEF456 - Ford Ranger Ute
✓ Created: GHI789 - Holden Commodore Sedan
```

### Skip Mode
```
✓ Created: ABC123 - Toyota Hilux Ute
⏭ Skipped: DEF456 (already exists)
✓ Created: GHI789 - Holden Commodore Sedan
```

## Data Mapping

The system automatically extracts the following from the "Description of vehicle" column:
- **Make**: Toyota, Ford, Holden, etc.
- **Model**: Hilux, Ranger, Commodore, etc.
- **Year**: 2010-2025
- **Color**: White, Black, Silver, etc.
- **Body Type**: Ute, Van, Sedan, SUV, etc.

## Error Handling

- Invalid data is reported with specific error messages
- Import continues with other records if some fail
- Transaction rollback ensures data consistency
- Detailed summary provided at the end

## Manual Usage (Python)

```python
from tracking.excel_reader import ExcelReader

# Initialize reader
reader = ExcelReader("path/to/file.xlsx")

# Read and process data
reader.read_excel(max_columns=25, nrows=100)
reader.parse_description_column('Description of vehicle')
django_df = reader.transform_for_django()

# Import with update (default)
results = reader.import_to_django(django_df, dry_run=False, update_existing=True)

# Import with skip existing
results = reader.import_to_django(django_df, dry_run=False, update_existing=False)
```