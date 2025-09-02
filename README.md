# 📘 AssetCap Server – Setup & Maintenance Manual

## 🔹 Server Environment
- **OS:** Ubuntu 22.04 LTS (server)  
- **Linux user:** `developer` (`ssh developer@142.103.68.1`)  
- **Web Server / Reverse Proxy:** Nginx 1.24  
- **Application Server:** Gunicorn (systemd services)  
- **SSL/TLS Certificates:** Let’s Encrypt (Certbot)  
- **Database:** SQLite (for QR codes)  
- **Python Apps:** Each isolated in its own virtualenv (`venv`)  

---

## 🔹 Applications Installed

### 1. Asset Capture App
- **Port:** `8000`  
- **Domain:** `appprod.assetcap.facilities.ubc.ca`  
- **Service:** `assetcap-app`  
- **Path:** `/home/developer/review/Asset_dasboard_browser_ME`  
- **Gunicorn target:** `asset_plate_reviewer:app`  
- **Restart:**  
  ```bash
  sudo systemctl restart assetcap-app
2. Asset Reviewer – Mechanical (ME)
Port: 8001

Domain: reviewme.assetcap.facilities.ubc.ca

Service: assetcap-reviewme

Path: /home/developer/review/Asset_dasboard_browser_ME

Gunicorn target: asset_plate_reviewer:app

Restart:

bash
Copy code
sudo systemctl restart assetcap-reviewme
3. Asset Reviewer – Backflow (BF)
Port: 8004

Domain: reviewbf.assetcap.facilities.ubc.ca

Service: assetcap-bf

Path: /home/developer/review/Asset_dasboard_browser_BF

Gunicorn target: asset_plate_reviewer_bf:app

Restart:

bash
Copy code
sudo systemctl restart assetcap-bf
4. Asset Portal Dashboard (Main)
Port: 8002

Domain: dashboardprod.assetcap.facilities.ubc.ca

Service: assetcap-dashboard

Path: /home/developer/Dashboard

Gunicorn target: Asset_portal_dashboard:app

Requirements: /home/developer/review/Asset_dasboard_browser_ME/requirements.txt

Restart:

bash
Copy code
sudo systemctl restart assetcap-dashboard
5. Asset Reviewer – Electrical (EL)
Port: 8005

Domain: reviewel.assetcap.facilities.ubc.ca

Service: assetcap-el

Path: /home/developer/review/Asset_dashboard_browser_EL

Gunicorn target: Asset_dashboard_EL:app

Requirements: /home/developer/review/Asset_dashboard_browser_EL/requirements.txt

Restart:

bash
Copy code
sudo systemctl restart assetcap-el
🔹 Directory Structure
bash
Copy code
/home/developer/
 ├─ Dashboard/                         # Central portal
 │   ├─ venv/                          # Virtual environment
 │   ├─ Asset_portal_dashboard.py      # Main code
 │   └─ charts/approval.py             # Chart utilities
 │
 ├─ review/Asset_dasboard_browser_ME/  # Mechanical app
 │   └─ asset_plate_reviewer.py
 │
 ├─ review/Asset_dasboard_browser_BF/  # Backflow app
 │   └─ asset_plate_reviewer_bf.py
 │
 ├─ review/Asset_dashboard_browser_EL/ # Electrical app
 │   └─ Asset_dashboard_EL.py
 │
 ├─ Output_jason_api/                  # JSON output data
 └─ Capture_photos_upload/             # Image uploads
🔹 System Packages Installed
bash
Copy code
sudo apt update
sudo apt install -y python3 python3-venv python3-pip \
                    nginx certbot python3-certbot-nginx \
                    tesseract-ocr libtesseract-dev \
                    libgl1   # required by OpenCV
Python packages (inside each app’s venv):
flask

gunicorn

python-dotenv

openai

opencv-python

pillow

pytesseract

numpy

🔹 Logs & Debugging
Check service logs
bash
Copy code
sudo journalctl -u assetcap-el -n 100 --no-pager
sudo journalctl -u assetcap-dashboard -f   # live logs
Check listening ports
bash
Copy code
sudo ss -ltnp | grep ':8005'
Nginx error logs
bash
Copy code
sudo tail -n 100 /var/log/nginx/error.log
sudo tail -n 100 /var/log/nginx/dashboardprod.error.log
🔹 Deployment Workflow (after code updates)
Go to the app folder:

bash
Copy code
cd /home/developer/review/Asset_dashboard_browser_EL
Activate the venv and update dependencies:

bash
Copy code
source venv/bin/activate
pip install -r requirements.txt
deactivate
Restart the related service:

bash
Copy code
sudo systemctl restart assetcap-el