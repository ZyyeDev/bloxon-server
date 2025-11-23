# Bloxon Server

Backend for [Bloxon](https://github.com/ZyyeDev/bloxon) - this wasn't really meant to be a standalone server, it's specifically the server for that game. But if you want to fork it for your own project, go ahead.

## What it does

- User accounts and auth
- Avatar customization + shop for accessories
- Virtual currency with Google Play payments
- Friends system (add people, join their servers)
- Private servers you can rent
- Moderation system
- WebSocket messages for broadcasts
- Admin dashboard to manage everything
- Auto-generates profile pictures using Godot
- Handles payments and ad rewards

## Setup

**Note:** This is designed to work with the [Bloxon game client](https://github.com/ZyyeDev/bloxon). You'll need both to actually run the full game.

### Easy way (on Hetzner)

1. Clone it:
```bash
git clone https://github.com/ZyyeDev/bloxon-server
cd bloxon-server
```

2. Make your `.env`:
```bash
cp .env.example .env
nano .env
```

3. Run the deploy script:
```bash
chmod +x deploy.sh
./deploy.sh
```

4. Upload your server binary thru the dashboard on http://server-ip:8080/dashboard


Done. It sets up everything else automatically.

### Manual setup

If you want to do it yourself:

1. Install requirements:
```bash
pip install -r requirements.txt
```

2. Make the directories:
```bash
mkdir -p /mnt/volume/{pfps,models,accessories,icons,database,backups,binaries}
```

3. Configure `.env` (check `.env.example` for what you need)

4. Start it:
```bash
python main.py
```

5. Upload your server binary thru the dashboard on http://server-ip:8080/dashboard

Server runs on `http://0.0.0.0:8080`

## API stuff

### Auth
- `POST /auth/register` - make account (has CAPTCHA after first one from your IP)
- `POST /auth/login` - login, get token
- `POST /auth/validate` - check if token still works

### Game servers
- `POST /request_server` - get connected to a server
- `GET /maintenance_status` - check if server is down for maintenance

### Player
- `POST /player/get_profile` - get someone's profile data
- `POST /player/update_avatar` - change avatar colors/accessories
- `POST /player/get_pfp` - get profile pic URL

### Currency
- `POST /currency/get` - check balance
- `POST /payments/purchase` - verify Google Play purchase
- `POST /payments/ad_reward` - claim ad reward
- `GET /payments/packages` - list currency packages

### Avatar & Shop
- `POST /avatar/list_market` - browse shop
- `POST /avatar/buy_item` - buy accessory
- `POST /avatar/equip` - equip accessory
- `POST /avatar/unequip` - unequip accessory

### Friends
- `POST /friends/send_request` - send friend request
- `POST /friends/accept_request` - accept request
- `POST /friends/get` - get friends list
- `POST /friends/join_server` - join friend's server

### Private Servers
- `POST /private_server/subscribe` - rent private server (250 currency for 30 days)
- `POST /private_server/cancel` - cancel subscription
- `POST /private_server/status` - check if you have one active

## How it works

(add diagram pls)

# Admin Dashboard

Go to `http://your-server:8080/dashboard`

Password gets auto-generated on first run, saved in `server_data/dashboard.pwd`

You can:
- See live stats for servers and VMs
- Give a player currency
- Upload/manage accessories for the shop
- Send messages to everyone
- Turn on maintenance mode
- Check system resources 