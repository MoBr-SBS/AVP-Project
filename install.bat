sudo apt update
sudo apt upgrade -y

sudo apt install python3.13-dev -y

pip install board
pip install Adafruit-Blinka

sudo apt install swig
sudo apt install liblgpio-dev
pip install lgpio

pip install aiohttp
pip install adafruit-circuitpython-servokit


pip install requests
pip install luma.core
pip install luma.oled
pip install gpiozero

sudo apt install ffmpeg -y
wget https://github.com/AlexxIT/go2rtc/releases/latest/download/go2rtc_linux_arm64
mv go2rtc_linux_arm64 go2rtc
chmod +x go2rtc
