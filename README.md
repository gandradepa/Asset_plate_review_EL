Electrical Asset Review DashboardThis web application provides a dashboard for reviewing, editing, and approving electrical asset data captured from the field. It is designed to streamline the quality assurance process by presenting asset information and associated photos in a user-friendly interface.FeaturesDashboard View: Displays all assets in a searchable, sortable, and filterable table.Filtering: Filter assets by building, approval status, flagged status, modified status, and whether they are missing photos.Review Interface: A detailed view for each asset, showing all data fields and associated images (Asset Plate, UBC Asset Tag, Panel Schedule).Data Editing: Users can edit asset information directly in the review interface. Changes are saved back to the source JSON files and synchronized with a central SQLite database.Image Viewer: Includes zoom and rotate functionality for easier inspection of asset photos.Quick Approval: Toggle the "Approved" status directly from the main dashboard.Data Sync: Automatically updates a SQLite database when asset data is modified, ensuring data consistency.Tech StackBackend: Python 3, FlaskFrontend: HTML5, CSS3, JavaScriptUI Framework: Bootstrap 5Libraries: jQuery, DataTables.jsDatabase: SQLiteProject StructureASSET_PLATE_REVIEW_EL/
│
├── Asset_dashboard_EL.py       # Main Flask application file
│
├── review_asset_templates/
│   ├── dashboard.html          # HTML template for the main dashboard
│   ├── review.html             # HTML template for the asset review page
│   └── static/
│       └── ubc-logo.png        # Static image assets
│
├── requirements.txt            # Python dependencies
└── readme.md                   # This file
Setup and InstallationClone the repository:git clone <repository-url>
cd ASSET_PLATE_REVIEW_EL
Install dependencies:It is recommended to use a virtual environment.python -m venv venv
source venv/bin/activate  # On Windows use `venv\Scripts\activate`
pip install -r requirements.txt
Configure Environment Variables:The application relies on environment variables to locate data directories. Set the following variables before running the application:JSON_DIR: Path to the directory containing the asset JSON files.IMG_DIR: Path to the directory containing the asset photos.DB_PATH: Full path to the SQLite database file (QR_codes.db).Example (.bashrc or .zshrc):export JSON_DIR="/path/to/your/json_files"
export IMG_DIR="/path/to/your/image_files"
export DB_PATH="/path/to/your/database/QR_codes.db"
Run the application:python Asset_dashboard_EL.py
The application will be available at http://127.0.0.1:5000.