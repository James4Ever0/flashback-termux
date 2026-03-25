su -c 'dumpsys window displays' > dumpsys_displays.txt
python3 extract_active_app_on_main_display.py
