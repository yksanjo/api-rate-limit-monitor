#!/usr/bin/env python3
"""
API Rate Limit Monitor
Monitors API rate limits and sends alerts via Slack/Discord
"""

import os
import time
import json
import argparse
import requests
from datetime import datetime
from typing import Dict, Optional, List
from dotenv import load_dotenv
import schedule

try:
    from slack_sdk import WebClient
    from slack_sdk.errors import SlackApiError
    SLACK_AVAILABLE = True
except ImportError:
    SLACK_AVAILABLE = False

try:
    import discord
    from discord.ext import tasks
    DISCORD_AVAILABLE = True
except ImportError:
    DISCORD_AVAILABLE = False

load_dotenv()

class RateLimitMonitor:
    def __init__(self):
        self.apis = self.load_apis()
        self.slack_client = None
        self.discord_client = None
        self.slack_channel = os.getenv('SLACK_CHANNEL_ID')
        self.discord_channel_id = int(os.getenv('DISCORD_CHANNEL_ID', 0)) if os.getenv('DISCORD_CHANNEL_ID') else None
        
        if os.getenv('SLACK_BOT_TOKEN') and SLACK_AVAILABLE:
            self.slack_client = WebClient(token=os.getenv('SLACK_BOT_TOKEN'))
        
        if os.getenv('DISCORD_BOT_TOKEN') and DISCORD_AVAILABLE:
            intents = discord.Intents.default()
            self.discord_client = discord.Client(intents=intents)
    
    def load_apis(self) -> Dict:
        """Load API configurations from file"""
        if os.path.exists('apis.json'):
            with open('apis.json', 'r') as f:
                return json.load(f)
        return {}
    
    def save_apis(self):
        """Save API configurations to file"""
        with open('apis.json', 'w') as f:
            json.dump(self.apis, f, indent=2)
    
    def add_api(self, name: str, endpoint: str, headers: Dict, threshold: float = 0.95):
        """Add an API to monitor"""
        self.apis[name] = {
            'endpoint': endpoint,
            'headers': headers,
            'threshold': threshold,
            'last_check': None,
            'last_remaining': None,
            'last_limit': None
        }
        self.save_apis()
        print(f"✅ Added API: {name}")
    
    def remove_api(self, name: str):
        """Remove an API from monitoring"""
        if name in self.apis:
            del self.apis[name]
            self.save_apis()
            print(f"✅ Removed API: {name}")
        else:
            print(f"❌ API '{name}' not found")
    
    def check_rate_limit(self, name: str, config: Dict) -> Optional[Dict]:
        """Check rate limit for a specific API"""
        try:
            response = requests.get(config['endpoint'], headers=config['headers'], timeout=10)
            response.raise_for_status()
            
            # Try to extract rate limit info from headers
            remaining = None
            limit = None
            
            # Common header formats
            header_variants = [
                ('X-RateLimit-Remaining', 'X-RateLimit-Limit'),
                ('RateLimit-Remaining', 'RateLimit-Limit'),
                ('X-Rate-Limit-Remaining', 'X-Rate-Limit-Limit'),
            ]
            
            for rem_header, lim_header in header_variants:
                if rem_header in response.headers and lim_header in response.headers:
                    remaining = int(response.headers[rem_header])
                    limit = int(response.headers[lim_header])
                    break
            
            # Try JSON response (GitHub style)
            if remaining is None and response.headers.get('Content-Type', '').startswith('application/json'):
                data = response.json()
                if 'rate' in data:
                    remaining = data['rate'].get('remaining')
                    limit = data['rate'].get('limit')
                elif 'resources' in data:
                    # GitHub API format
                    for resource in data['resources'].values():
                        if 'remaining' in resource and 'limit' in resource:
                            remaining = resource.get('remaining')
                            limit = resource.get('limit')
                            break
            
            if remaining is not None and limit is not None:
                return {
                    'remaining': remaining,
                    'limit': limit,
                    'usage': (limit - remaining) / limit if limit > 0 else 0
                }
        except Exception as e:
            print(f"❌ Error checking {name}: {e}")
        
        return None
    
    def send_slack_alert(self, name: str, remaining: int, limit: int, usage: float):
        """Send alert to Slack"""
        if not self.slack_client or not self.slack_channel:
            return
        
        try:
            emoji = "🚨" if usage >= 0.95 else "⚠️"
            message = f"{emoji} *Rate Limit Alert*\n"
            message += f"*API:* {name}\n"
            message += f"*Remaining:* {remaining:,} / {limit:,}\n"
            message += f"*Usage:* {usage:.1%}\n"
            message += f"*Time:* {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
            
            self.slack_client.chat_postMessage(
                channel=self.slack_channel,
                text=message
            )
        except SlackApiError as e:
            print(f"❌ Slack error: {e}")
    
    def send_discord_alert(self, name: str, remaining: int, limit: int, usage: float):
        """Send alert to Discord"""
        if not self.discord_client or not self.discord_channel_id:
            return
        
        try:
            channel = self.discord_client.get_channel(self.discord_channel_id)
            if channel:
                emoji = "🚨" if usage >= 0.95 else "⚠️"
                message = f"{emoji} **Rate Limit Alert**\n"
                message += f"**API:** {name}\n"
                message += f"**Remaining:** {remaining:,} / {limit:,}\n"
                message += f"**Usage:** {usage:.1%}\n"
                message += f"**Time:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
                asyncio.run(channel.send(message))
        except Exception as e:
            print(f"❌ Discord error: {e}")
    
    def check_all_apis(self):
        """Check all monitored APIs"""
        for name, config in self.apis.items():
            result = self.check_rate_limit(name, config)
            if result:
                remaining = result['remaining']
                limit = result['limit']
                usage = result['usage']
                
                config['last_check'] = datetime.now().isoformat()
                config['last_remaining'] = remaining
                config['last_limit'] = limit
                
                # Check if threshold exceeded
                if usage >= config['threshold']:
                    print(f"🚨 Alert: {name} at {usage:.1%} usage ({remaining}/{limit})")
                    self.send_slack_alert(name, remaining, limit, usage)
                    self.send_discord_alert(name, remaining, limit, usage)
                else:
                    print(f"✓ {name}: {remaining}/{limit} ({usage:.1%})")
        
        self.save_apis()
    
    def run(self, interval: int = 60):
        """Start monitoring loop"""
        print(f"🚀 Starting API Rate Limit Monitor (checking every {interval}s)")
        print(f"📊 Monitoring {len(self.apis)} API(s)")
        
        schedule.every(interval).seconds.do(self.check_all_apis)
        
        # Initial check
        self.check_all_apis()
        
        while True:
            schedule.run_pending()
            time.sleep(1)


def main():
    parser = argparse.ArgumentParser(description='API Rate Limit Monitor')
    parser.add_argument('--add-api', help='Add API to monitor')
    parser.add_argument('--endpoint', help='API endpoint URL')
    parser.add_argument('--header', action='append', help='Header in format KEY:VALUE')
    parser.add_argument('--threshold', type=float, default=0.95, help='Alert threshold (0-1)')
    parser.add_argument('--remove-api', help='Remove API from monitoring')
    parser.add_argument('--list', action='store_true', help='List monitored APIs')
    parser.add_argument('--interval', type=int, default=60, help='Check interval in seconds')
    
    args = parser.parse_args()
    
    monitor = RateLimitMonitor()
    
    if args.add_api and args.endpoint:
        headers = {}
        if args.header:
            for h in args.header:
                if ':' in h:
                    key, value = h.split(':', 1)
                    headers[key] = value
        monitor.add_api(args.add_api, args.endpoint, headers, args.threshold)
    elif args.remove_api:
        monitor.remove_api(args.remove_api)
    elif args.list:
        if monitor.apis:
            print("\n📊 Monitored APIs:")
            for name, config in monitor.apis.items():
                print(f"  • {name}: {config['endpoint']} (threshold: {config['threshold']:.0%})")
        else:
            print("No APIs configured")
    else:
        monitor.run(args.interval)


if __name__ == '__main__':
    import asyncio
    main()


