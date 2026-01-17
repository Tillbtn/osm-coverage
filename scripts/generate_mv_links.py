import csv
import urllib.parse
import os

def generate_links():
    input_file = 'Gemeinde_Gemarkung_Kreis.csv'
    output_file = 'shapefile_links.txt'
    
    # Base URL pattern
    base_url = "https://www.geodaten-mv.de/dienste/alkis_nas_download?index=1&dataset=32538df8-6b74-4582-8591-c77e85fbf929&file={id}_SHP_{name}.zip"
    
    # Store unique municipalities to avoid duplicates
    # Key: id_Gemeinde, Value: Gemeinde_Name (original)
    municipalities = {}

    if not os.path.exists(input_file):
        print(f"Error: {input_file} not found.")
        return

    try:
        with open(input_file, 'r', encoding='utf-8') as f:
            # The file uses semicolons as delimiters
            reader = csv.DictReader(f, delimiter=';')
            
            for row in reader:
                # Based on file inspection, columns are 'id_Gemeinde' and 'Gemeinde_Name'
                id_gemeinde = row.get('id_Gemeinde')
                gemeinde_name = row.get('Gemeinde_Name')
                
                if id_gemeinde and gemeinde_name:
                    municipalities[id_gemeinde] = gemeinde_name
                    
    except Exception as e:
        print(f"Error reading CSV: {e}")
        return

    links = []
    
    # Sort by ID for consistent output
    for id_gemeinde in sorted(municipalities.keys()):
        original_name = municipalities[id_gemeinde]
        
        # Transformation: Replace comma, hyphen, space with underscore
        transformed_name = original_name.replace(',', '_').replace('-', '_').replace(' ', '_')
        
        # URL Encode (safe characters usually don't include special german chars, so quote will handle them)
        # Using quote ensures UTF-8 bytes are percent-encoded
        encoded_name = urllib.parse.quote(transformed_name)
        
        link = base_url.format(id=id_gemeinde, name=encoded_name)
        links.append(link)

    try:
        with open(output_file, 'w', encoding='utf-8') as f:
            for link in links:
                f.write(link + '\n')
        print(f"Successfully generated {len(links)} links in {output_file}")
    except Exception as e:
        print(f"Error writing output: {e}")

if __name__ == '__main__':
    generate_links()
