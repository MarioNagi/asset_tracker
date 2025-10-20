import pandas as pd
import re
from datetime import datetime
from django.core.exceptions import ValidationError
import os


class ExcelReader:
    """
    A class to read car data from Excel file and prepare it for Django database import.
    Handles parsing of description column containing multiple car attributes.
    """
    
    def __init__(self, excel_file_path):
        """
        Initialize the ExcelReader with the path to the Excel file.
        
        Args:
            excel_file_path (str): Path to the Excel file containing car data
        """
        self.excel_file_path = excel_file_path
        self.raw_df = None
        self.processed_df = None
        
    def read_excel(self, max_columns=50, nrows=None):
        """
        Read the Excel file and store it in raw_df.
        
        Args:
            max_columns (int): Maximum number of columns to read
            nrows (int): Maximum number of rows to read (None for all)
        
        Returns:
            pandas.DataFrame: The raw data from Excel
        """
        try:
            if not os.path.exists(self.excel_file_path):
                raise FileNotFoundError(f"Excel file not found: {self.excel_file_path}")
            
            # First, try to read just the headers to see what columns exist
            try:
                headers_df = pd.read_excel(self.excel_file_path, nrows=0)
                all_columns = headers_df.columns.tolist()
                print(f"Found {len(all_columns)} columns in Excel file")
                
                # Limit columns to avoid memory issues
                columns_to_read = all_columns[:max_columns] if len(all_columns) > max_columns else all_columns
                print(f"Reading first {len(columns_to_read)} columns: {columns_to_read}")
                
                self.raw_df = pd.read_excel(self.excel_file_path, usecols=columns_to_read, nrows=nrows)
                
                # Filter out empty rows where 'Rego' column is empty
                rego_columns = [col for col in self.raw_df.columns if 'rego' in col.lower()]
                if rego_columns:
                    rego_col = rego_columns[0]  # Use the first rego column found
                    print(f"Using '{rego_col}' column to filter empty rows")
                    
                    # Count rows before filtering
                    original_count = len(self.raw_df)
                    
                    # Filter out rows where rego is empty/null
                    self.raw_df = self.raw_df.dropna(subset=[rego_col])
                    self.raw_df = self.raw_df[self.raw_df[rego_col].astype(str).str.strip() != '']
                    
                    # Count rows after filtering
                    filtered_count = len(self.raw_df)
                    removed_count = original_count - filtered_count
                    
                    print(f"Filtered out {removed_count} empty rows (from {original_count} to {filtered_count} rows)")
                else:
                    print("Warning: No 'Rego' column found for filtering empty rows")
                
            except Exception as e:
                print(f"Error reading with column limit, trying basic read: {str(e)}")
                # Fallback: try reading with row limit only
                self.raw_df = pd.read_excel(self.excel_file_path, nrows=nrows or 100)
            
            print(f"Successfully read Excel file with {len(self.raw_df)} rows and {len(self.raw_df.columns)} columns")
            print(f"Columns: {self.raw_df.columns.tolist()}")
            return self.raw_df
            
        except Exception as e:
            print(f"Error reading Excel file: {str(e)}")
            raise
    
    def examine_data_structure(self):
        """
        Examine the structure of the data and print useful information.
        """
        if self.raw_df is None:
            print("No data loaded. Please call read_excel() first.")
            return
        
        print("\n=== DATA STRUCTURE ANALYSIS ===")
        print(f"Shape: {self.raw_df.shape}")
        print(f"\nColumns: {self.raw_df.columns.tolist()}")
        print(f"\nData types:\n{self.raw_df.dtypes}")
        print(f"\nFirst 5 rows:")
        print(self.raw_df.head())
        
        # Check for description column
        description_cols = [col for col in self.raw_df.columns if 'description' in col.lower() or 'desc' in col.lower()]
        if description_cols:
            print(f"\nDescription columns found: {description_cols}")
            for col in description_cols:
                print(f"\nSample {col} values:")
                sample_values = self.raw_df[col].dropna().head(3).tolist()
                for i, val in enumerate(sample_values, 1):
                    print(f"  {i}. {val}")
        
        # Check for missing values
        print(f"\nMissing values per column:")
        missing_data = self.raw_df.isnull().sum()
        for col, missing_count in missing_data.items():
            if missing_count > 0:
                print(f"  {col}: {missing_count}")
    
    def parse_description_column(self, description_col_name):
        """
        Parse the description column to extract car attributes like make, model, year, color, etc.
        
        Args:
            description_col_name (str): Name of the description column
            
        Returns:
            pandas.DataFrame: DataFrame with extracted attributes
        """
        if self.raw_df is None:
            raise ValueError("No data loaded. Please call read_excel() first.")
        
        if description_col_name not in self.raw_df.columns:
            raise ValueError(f"Column '{description_col_name}' not found in data")
        
        # Create a copy of the dataframe for processing
        df = self.raw_df.copy()
        
        # Initialize new columns
        df['extracted_make'] = ''
        df['extracted_model'] = ''
        df['extracted_year'] = None
        df['extracted_color'] = ''
        df['extracted_body_type'] = ''
        
        # Common car makes (can be expanded)
        car_makes = [
            'toyota', 'holden', 'ford', 'mazda', 'mitsubishi', 'nissan', 'honda', 
            'subaru', 'hyundai', 'kia', 'volkswagen', 'bmw', 'mercedes', 'audi',
            'lexus', 'infiniti', 'chevrolet', 'chrysler', 'dodge', 'jeep', 'ram',
            'peugeot', 'renault', 'citroen', 'skoda', 'volvo', 'jaguar', 'land rover',
            'isuzu', 'suzuki', 'daihatsu', 'great wall', 'chery', 'haval'
        ]
        
        # Common colors
        colors = [
            'white', 'black', 'silver', 'grey', 'gray', 'blue', 'red', 'green',
            'yellow', 'orange', 'brown', 'gold', 'beige', 'maroon', 'purple',
            'pink', 'tan', 'bronze', 'champagne', 'pearl', 'metallic'
        ]
        
        # Common body types
        body_types = [
            'sedan', 'hatchback', 'suv', 'ute', 'van', 'truck', 'wagon', 
            'coupe', 'convertible', 'ewp', 'trailer', 'utility'
        ]
        
        for index, row in df.iterrows():
            description = str(row[description_col_name]).lower() if pd.notna(row[description_col_name]) else ''
            
            if description and description != 'nan':
                # Extract year (4-digit number, typically 1980-2030)
                year_match = re.search(r'\b(19[8-9]\d|20[0-3]\d)\b', description)
                if year_match:
                    df.at[index, 'extracted_year'] = int(year_match.group(1))
                
                # Extract make
                for make in car_makes:
                    if make in description:
                        df.at[index, 'extracted_make'] = make.title()
                        break
                
                # Extract color
                for color in colors:
                    if color in description:
                        df.at[index, 'extracted_color'] = color.title()
                        break
                
                # Extract body type
                for body_type in body_types:
                    if body_type in description:
                        df.at[index, 'extracted_body_type'] = body_type.title()
                        break
                
                # Try to extract model (this is more complex and might need manual refinement)
                # Look for words after the make
                make = df.at[index, 'extracted_make'].lower()
                if make:
                    # Find make position and extract following words
                    make_pos = description.find(make)
                    if make_pos != -1:
                        after_make = description[make_pos + len(make):].strip()
                        # Extract potential model (next 1-2 words, excluding common words)
                        words = re.findall(r'\b[a-zA-Z0-9]+\b', after_make)
                        skip_words = ['car', 'vehicle', 'auto', 'motor', 'the', 'and', 'or', 'with']
                        model_words = [w for w in words[:3] if w.lower() not in skip_words and len(w) > 1]
                        if model_words:
                            df.at[index, 'extracted_model'] = ' '.join(model_words[:2]).title()
        
        self.processed_df = df
        return df
    
    def transform_for_django(self, column_mapping=None):
        """
        Transform the processed dataframe to match Django Car model fields.
        
        Args:
            column_mapping (dict): Mapping of Excel columns to Django model fields
            
        Returns:
            pandas.DataFrame: Transformed dataframe ready for Django import
        """
        if self.processed_df is None:
            raise ValueError("No processed data available. Please run parse_description_column() first.")
        
        # Default column mapping (adjusted for actual Excel columns)
        if column_mapping is None:
            column_mapping = {
                'Rego': 'rego',
                'rego': 'rego',
                'registration': 'rego',
                'reg': 'rego',
                'plate': 'rego',
                'Rego exp.': 'rego_expiry_date',
                'rego_expiry': 'rego_expiry_date',
                'expiry': 'rego_expiry_date',
                'expiry_date': 'rego_expiry_date',
                'inv. date ': 'purchase_date',
                'purchase_date': 'purchase_date',
                'purchase_price': 'purchase_price',
                'price': 'purchase_price',
                'cost': 'purchase_price',
                'state': 'state',
                'Current odometer': 'current_odometer',
                'current_odometer': 'current_odometer',
                'odometer': 'current_odometer',
                'km': 'current_odometer',
                'kilometers': 'current_odometer',
                'service odometer': 'service_odometer',
                'service_odometer': 'service_odometer',
                'vin': 'vin_number',
                'vin_number': 'vin_number',
                'chassis': 'vin_number',
            }
        
        df = self.processed_df.copy()
        
        # Create Django-compatible dataframe
        django_df = pd.DataFrame()
        
        # Map existing columns
        for excel_col, django_field in column_mapping.items():
            if excel_col in df.columns:
                django_df[django_field] = df[excel_col]
        
        # Add extracted attributes
        django_df['make'] = df['extracted_make']
        django_df['model'] = df['extracted_model']
        django_df['manufacturing_year'] = df['extracted_year']
        django_df['color'] = df['extracted_color']
        django_df['body'] = df['extracted_body_type']
        
        # Set default values for required fields
        if 'state' not in django_df.columns:
            django_df['state'] = 'NSW'  # Default state
        
        if 'current_odometer' not in django_df.columns:
            django_df['current_odometer'] = 0
        
        if 'service_odometer' not in django_df.columns:
            django_df['service_odometer'] = 10000
        
        # Clean and validate data
        django_df = self._clean_data(django_df)
        
        return django_df
    
    def _clean_data(self, df):
        """
        Clean and validate the data for Django import.
        
        Args:
            df (pandas.DataFrame): Dataframe to clean
            
        Returns:
            pandas.DataFrame: Cleaned dataframe
        """
        # Remove rows with missing critical data (rego)
        critical_fields = ['rego']
        for field in critical_fields:
            if field in df.columns:
                # Remove rows where rego is null or empty string
                df = df.dropna(subset=[field])
                df = df[df[field].astype(str).str.strip() != '']
                df = df[df[field].astype(str).str.lower() != 'nan']
        
        # Clean registration numbers (remove spaces, convert to uppercase)
        if 'rego' in df.columns:
            df['rego'] = df['rego'].astype(str).str.replace(' ', '').str.upper()
            # Filter out obviously invalid rego values
            df = df[df['rego'].str.len() >= 3]  # Minimum rego length
            df = df[~df['rego'].str.contains('UNNAMED', na=False)]  # Remove unnamed columns
        
        # Handle dates
        date_fields = ['rego_expiry_date', 'purchase_date']
        for field in date_fields:
            if field in df.columns:
                # Convert to datetime and then to date, handling NaT values
                df[field] = pd.to_datetime(df[field], errors='coerce')
                # Replace NaT values with None before converting to date
                df[field] = df[field].where(df[field].notna(), None)
                # Convert to date only for non-null values
                df[field] = df[field].apply(lambda x: x.date() if pd.notna(x) else None)
        
        # Handle numeric fields
        numeric_fields = ['current_odometer', 'service_odometer', 'manufacturing_year', 'purchase_price']
        for field in numeric_fields:
            if field in df.columns:
                df[field] = pd.to_numeric(df[field], errors='coerce')
        
        # Fill missing values
        df = df.fillna({
            'make': 'Unknown',
            'model': 'Unknown',
            'color': 'Unknown',
            'body': 'Other',
            'current_odometer': 0,
            'service_odometer': 10000,
        })
        
        print(f"After cleaning: {len(df)} valid rows with registration numbers")
        return df
    
    def import_to_django(self, django_df=None, dry_run=True, update_existing=True):
        """
        Import the processed data to Django Car model.
        
        Args:
            django_df (pandas.DataFrame): Dataframe to import (uses transformed data if None)
            dry_run (bool): If True, only validate data without saving
            update_existing (bool): If True, update existing records; if False, skip them
            
        Returns:
            dict: Import results summary
        """
        from tracking.models import Car
        from django.db import transaction
        
        if django_df is None:
            django_df = self.transform_for_django()
        
        results = {
            'total_rows': len(django_df),
            'created': 0,
            'updated': 0,
            'skipped': 0,
            'errors': []
        }
        
        if dry_run:
            print("DRY RUN MODE - No data will be saved")
            print(f"Would process {len(django_df)} rows")
            print(f"Update existing records: {update_existing}")
            print("\nSample data to be imported:")
            print(django_df.head())
            return results
        
        with transaction.atomic():
            for index, row in django_df.iterrows():
                try:
                    # Create car data dictionary, excluding NaN values
                    car_data = {}
                    for field_name in ['rego', 'rego_expiry_date', 'purchase_date', 'state', 
                                     'current_odometer', 'service_odometer', 'vin_number', 
                                     'make', 'model', 'manufacturing_year', 'color', 'body']:
                        if field_name in row and str(row[field_name]) != 'nan' and row[field_name] is not None:
                            car_data[field_name] = row[field_name]
                    
                    # Set required defaults
                    if 'rego_expiry_date' not in car_data or car_data['rego_expiry_date'] is None:
                        from datetime import date
                        car_data['rego_expiry_date'] = date.today()
                    
                    if update_existing:
                        # Use update_or_create to handle both new and existing records
                        car, created = Car.objects.update_or_create(
                            rego=row['rego'],
                            defaults=car_data
                        )
                        
                        if created:
                            results['created'] += 1
                            print(f"✓ Created: {car.rego} - {car.make} {car.model}")
                        else:
                            results['updated'] += 1
                            print(f"↻ Updated: {car.rego} - {car.make} {car.model}")
                    else:
                        # Check if car already exists and skip if it does
                        if Car.objects.filter(rego=row['rego']).exists():
                            results['skipped'] += 1
                            print(f"⏭ Skipped: {row['rego']} (already exists)")
                            continue
                        
                        # Create new car
                        car = Car.objects.create(**car_data)
                        results['created'] += 1
                        print(f"✓ Created: {car.rego} - {car.make} {car.model}")
                    
                except Exception as e:
                    error_msg = f"Error importing row {index}: {str(e)}"
                    results['errors'].append(error_msg)
                    print(error_msg)
        
        return results
    
    def get_data_statistics(self):
        """
        Get statistics about the loaded data.
        
        Returns:
            dict: Statistics about the data
        """
        if self.raw_df is None:
            return {"error": "No data loaded"}
        
        stats = {
            "total_rows": len(self.raw_df),
            "total_columns": len(self.raw_df.columns),
        }
        
        # Check for rego column
        rego_columns = [col for col in self.raw_df.columns if 'rego' in col.lower()]
        if rego_columns:
            rego_col = rego_columns[0]
            valid_regos = self.raw_df[rego_col].dropna()
            valid_regos = valid_regos[valid_regos.astype(str).str.strip() != '']
            stats["valid_rego_rows"] = len(valid_regos)
            stats["empty_rego_rows"] = len(self.raw_df) - len(valid_regos)
        
        return stats
    
    def get_import_summary(self):
        """
        Get a summary of the data ready for import.
        
        Returns:
            dict: Summary information
        """
        if self.processed_df is None:
            return {"error": "No processed data available"}
        
        summary = {
            "total_records": len(self.processed_df),
            "makes_found": self.processed_df['extracted_make'].value_counts().to_dict(),
            "years_found": self.processed_df['extracted_year'].value_counts().to_dict(),
            "colors_found": self.processed_df['extracted_color'].value_counts().to_dict(),
            "body_types_found": self.processed_df['extracted_body_type'].value_counts().to_dict(),
        }
        
        return summary
        """
        Get a summary of the data ready for import.
        
        Returns:
            dict: Summary information
        """
        if self.processed_df is None:
            return {"error": "No processed data available"}
        
        summary = {
            "total_records": len(self.processed_df),
            "makes_found": self.processed_df['extracted_make'].value_counts().to_dict(),
            "years_found": self.processed_df['extracted_year'].value_counts().to_dict(),
            "colors_found": self.processed_df['extracted_color'].value_counts().to_dict(),
            "body_types_found": self.processed_df['extracted_body_type'].value_counts().to_dict(),
        }
        
        return summary


# Example usage
if __name__ == "__main__":
    # Initialize reader with Excel file path
    excel_path = r"c:\Users\Mario\python projects\Koinonia\fixed_assets\asset_tracker\tracking\CARS 22-11- 2024.xlsx"
    reader = ExcelReader(excel_path)
    
    # Read and examine the Excel file
    reader.read_excel()
    reader.examine_data_structure()