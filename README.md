# LXMF Echo Bot

A simple [LXMF](https://github.com/markqvist/LXMF/) echo bot for [Reticulum](https://github.com/markqvist/Reticulum/).

## How to use it?

```
# clone project
git clone https://github.com/liamcottle/lxmf-echobot

# install python deps
cd lxmf-echobot
pip install -r requirements.txt

# run echo bot and auto announce every hour
python3 echobot.py --identity-file echobot_identity --display-name "Echo Bot" --announce-interval-seconds 3600
```
