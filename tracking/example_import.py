"""
Example usage of the ExcelReader class for importing car data.

This script demonstrates how to use the ExcelReader to:
1. Read car data from Excel
2. Parse the description column to extract car attributes
3. Transform the data for Django import
4. Import the data into the database

Usage examples:
1. Dry run with limited rows:
   python manage.py import_cars --dry-run --max-rows 10

2. Import all data:
   python manage.py import_cars

3. Import specific file with custom settings:
   python manage.py import_cars --file "path/to/your/file.xlsx" --max-rows 50

4. Manual usage in Python:
   from tracking.excel_reader import ExcelReader
   reader = ExcelReader("path/to/excel/file.xlsx")
   reader.read_excel()
   reader.parse_description_column('Description of vehicle')
   django_df = reader.transform_for_django()
   results = reader.import_to_django(django_df, dry_run=False)
"""

from tracking.excel_reader import ExcelReader

def example_usage():
    """Example of how to use the ExcelReader manually"""
    
    # Initialize the reader
    excel_path = r"tracking\CARS 22-11- 2024.xlsx"
    reader = ExcelReader(excel_path)
    
    # Read the Excel file
    print("Step 1: Reading Excel file...")
    reader.read_excel(max_columns=25, nrows=10)  # Limit for testing
    
    # Examine the structure
    print("\nStep 2: Examining data structure...")
    reader.examine_data_structure()
    
    # Parse description column
    print("\nStep 3: Parsing description column...")
    reader.parse_description_column('Description of vehicle')
    
    # Transform for Django
    print("\nStep 4: Transforming for Django...")
    django_df = reader.transform_for_django()
    print("Django-ready data preview:")
    print(django_df[['rego', 'make', 'model', 'manufacturing_year', 'color', 'body']].head())
    
    # Get summary
    print("\nStep 5: Import summary...")
    summary = reader.get_import_summary()
    print(f"Total records: {summary['total_records']}")
    print(f"Makes found: {summary['makes_found']}")
    print(f"Years found: {summary['years_found']}")
    
    # Perform dry run import
    print("\nStep 6: Dry run import...")
    results = reader.import_to_django(django_df, dry_run=True)
    print(f"Import results: {results}")


if __name__ == "__main__":
    example_usage()