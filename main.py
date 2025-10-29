import os
import logging
import sqlite3
from datetime import datetime, timedelta
from dotenv import load_dotenv
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, ContextTypes, MessageHandler, filters
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger
import requests
import json
import asyncio

# Load environment variables
load_dotenv()

# Bot configuration
BOT_TOKEN = os.getenv('BOT_TOKEN', '8366535001:AAFyVWNNRATsI_XqIUiT_Qqa-PAjGcVAyDU')
FORCE_JOIN_CHANNEL = "@ronjumodz"
ADMIN_USER_ID = 7755338110
CONTACT_USERNAME = "@Ronju360"
AADHAAR_API_BASE_URL = "https://happy-ration-info.vercel.app/fetch?key=paidchx&aadhaar="
VEHICLE_API_BASE_URL = "https://vehicle-info.itxkaal.workers.dev/?num="
PAKISTAN_PHONE_API_BASE_URL = "https://kami-database.vercel.app/api/search?phone="

# Credit system configuration
INITIAL_CREDITS = 30
PHONE_LOOKUP_COST = 10
REFERRAL_CREDITS = 4

# Initialize logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

class OSINTBot:
    def __init__(self):
        self.init_db()
        self.scheduler = AsyncIOScheduler()
        self.setup_scheduler()
    
    def init_db(self):
        """Initialize SQLite database"""
        self.conn = sqlite3.connect('users.db', check_same_thread=False)
        self.cursor = self.conn.cursor()
        
        # Create users table
        self.cursor.execute('''
            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY,
                username TEXT,
                first_name TEXT,
                join_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                premium_status BOOLEAN DEFAULT FALSE,
                premium_expiry TIMESTAMP,
                force_joined BOOLEAN DEFAULT FALSE,
                free_trial_used BOOLEAN DEFAULT FALSE,
                credits INTEGER DEFAULT 0,
                referrer_id INTEGER DEFAULT NULL,
                referral_code TEXT UNIQUE
            )
        ''')
        
        # Create admin table
        self.cursor.execute('''
            CREATE TABLE IF NOT EXISTS admin (
                id INTEGER PRIMARY KEY,
                broadcast_text TEXT
            )
        ''')
        
        # Create referral tracking table
        self.cursor.execute('''
            CREATE TABLE IF NOT EXISTS referrals (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                referrer_id INTEGER,
                referred_id INTEGER,
                reward_claimed BOOLEAN DEFAULT FALSE,
                referral_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (referrer_id) REFERENCES users (user_id),
                FOREIGN KEY (referred_id) REFERENCES users (user_id)
            )
        ''')
        
        self.conn.commit()
        logger.info("Database initialized successfully")
    
    def setup_scheduler(self):
        """Setup scheduled tasks"""
        self.scheduler.add_job(self.check_premium_expiry, IntervalTrigger(hours=1))
        self.scheduler.start()
        logger.info("Scheduler started")
    
    async def check_premium_expiry(self):
        """Check and remove expired premium"""
        try:
            current_time = datetime.now()
            self.cursor.execute(
                "SELECT user_id FROM users WHERE premium_status = 1 AND premium_expiry < ?", 
                (current_time,)
            )
            expired_users = self.cursor.fetchall()
            
            for user_id, in expired_users:
                self.cursor.execute(
                    "UPDATE users SET premium_status = 0, premium_expiry = NULL WHERE user_id = ?",
                    (user_id,)
                )
                try:
                    await self.application.bot.send_message(
                        chat_id=user_id,
                        text="❌ Your premium access has expired. Contact @Ronju360 to upgrade to premium."
                    )
                except Exception as e:
                    logger.error(f"Could not send message to user {user_id}: {e}")
            
            self.conn.commit()
            logger.info(f"Checked premium expiry. {len(expired_users)} users expired")
        except Exception as e:
            logger.error(f"Error in check_premium_expiry: {e}")
    
    def generate_referral_code(self, user_id):
        """Generate a unique referral code for user"""
        import hashlib
        code = hashlib.md5(f"{user_id}{datetime.now()}".encode()).hexdigest()[:8].upper()
        return code
    
    async def start(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /start command"""
        user_id = update.effective_user.id
        username = update.effective_user.username
        first_name = update.effective_user.first_name
        
        # Check if user has a referrer
        referrer_id = None
        if context.args and len(context.args) > 0:
            try:
                referrer_code = context.args[0]
                self.cursor.execute("SELECT user_id FROM users WHERE referral_code = ?", (referrer_code,))
                referrer = self.cursor.fetchone()
                if referrer:
                    referrer_id = referrer[0]
            except:
                pass
        
        # Check if user exists
        self.cursor.execute("SELECT * FROM users WHERE user_id = ?", (user_id,))
        user = self.cursor.fetchone()
        
        if not user:
            # New user - give 24 hours premium and initial credits
            expiry_time = datetime.now() + timedelta(hours=24)
            referral_code = self.generate_referral_code(user_id)
            
            self.cursor.execute(
                """INSERT INTO users 
                (user_id, username, first_name, premium_status, premium_expiry, free_trial_used, credits, referrer_id, referral_code) 
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (user_id, username, first_name, True, expiry_time, True, INITIAL_CREDITS, referrer_id, referral_code)
            )
            self.conn.commit()
            
            # If referred, give credits to referrer
            if referrer_id:
                self.cursor.execute(
                    "UPDATE users SET credits = credits + ? WHERE user_id = ?",
                    (REFERRAL_CREDITS, referrer_id)
                )
                self.cursor.execute(
                    "INSERT INTO referrals (referrer_id, referred_id, reward_claimed) VALUES (?, ?, ?)",
                    (referrer_id, user_id, True)
                )
                self.conn.commit()
                
                try:
                    await self.application.bot.send_message(
                        chat_id=referrer_id,
                        text=f"🎉 You got {REFERRAL_CREDITS} credits! {first_name} joined using your referral link."
                    )
                except:
                    pass
            
            welcome_text = f"""
👋 Welcome {first_name}!

🎁 You have received:
• 24 hours FREE premium access!
• {INITIAL_CREDITS} free credits for Pakistan phone lookups

⏰ Your free trial will expire in 24 hours.

💰 You have: {INITIAL_CREDITS} credits
📱 Pakistan phone lookup costs: {PHONE_LOOKUP_COST} credits/search

📊 Available Services:
• Aadhaar Information (Free during trial)
• Vehicle Information (Free during trial)  
• Pakistan Phone Information ({PHONE_LOOKUP_COST} credits/search)

⚠️ Please join our channel first to verify yourself.
            """
        else:
            # Existing user
            self.cursor.execute("SELECT credits FROM users WHERE user_id = ?", (user_id,))
            user_credits = self.cursor.fetchone()[0]
            
            welcome_text = f"""
👋 Welcome back {first_name}!

💰 You have: {user_credits} credits
📱 Pakistan phone lookup costs: {PHONE_LOOKUP_COST} credits/search

📊 Available Services:
• Aadhaar Information
• Vehicle Information  
• Pakistan Phone Information

Check your status with /status
            """
        
        # Check if user has joined channel
        self.cursor.execute("SELECT force_joined FROM users WHERE user_id = ?", (user_id,))
        user_data = self.cursor.fetchone()
        
        if user_data and user_data[0]:
            # User already verified - show main menu
            await self.show_main_menu(update, context, welcome_text)
        else:
            # Ask to join channel
            keyboard = [
                [InlineKeyboardButton("✅ Verify Join", callback_data="verify_join")],
                [InlineKeyboardButton("🔗 Join Channel", url=f"https://t.me/{FORCE_JOIN_CHANNEL[1:]}")]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            await update.message.reply_text(
                f"{welcome_text}\n\n⚠️ Please join our channel and click verify:",
                reply_markup=reply_markup
            )
    
    async def show_main_menu(self, update: Update, context: ContextTypes.DEFAULT_TYPE, text=None):
        """Show main menu with service buttons"""
        user_id = update.effective_user.id
        
        # Get user status
        self.cursor.execute(
            "SELECT premium_status, premium_expiry, credits FROM users WHERE user_id = ?", 
            (user_id,)
        )
        user_data = self.cursor.fetchone()
        
        if not text:
            premium_status, expiry, credits = user_data
            status_text = "✅ ACTIVE" if premium_status else "❌ INACTIVE"
            
            if premium_status and expiry:
                time_left = expiry - datetime.now()
                hours_left = int(time_left.total_seconds() / 3600)
                days_left = int(hours_left / 24)
                
                if days_left > 0:
                    expiry_text = f"{days_left} days {hours_left % 24} hours"
                else:
                    expiry_text = f"{hours_left} hours"
            else:
                expiry_text = "N/A"
            
            text = f"""
🤖 OSINT Bot - Main Menu

💎 Premium Status: {status_text}
⏰ Time Left: {expiry_text}
💰 Credits: {credits}
📱 Phone Lookup Cost: {PHONE_LOOKUP_COST} credits

Choose a service:
            """
        
        keyboard = [
            [InlineKeyboardButton("🆔 Aadhaar Lookup", callback_data="service_aadhaar")],
            [InlineKeyboardButton("🚗 Vehicle Lookup", callback_data="service_vehicle")],
            [InlineKeyboardButton("📱 Pakistan Phone Lookup", callback_data="service_phone")],
            [InlineKeyboardButton("💎 Status & Credits", callback_data="service_status"), 
             InlineKeyboardButton("👥 Refer & Earn", callback_data="service_refer")],
            [InlineKeyboardButton("🆘 Help", callback_data="service_help")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        if update.callback_query:
            await update.callback_query.edit_message_text(text, reply_markup=reply_markup)
        else:
            await update.message.reply_text(text, reply_markup=reply_markup)
    
    async def handle_service_selection(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle service selection from buttons"""
        query = update.callback_query
        await query.answer()
        
        data = query.data
        user_id = query.from_user.id
        
        if data == "service_aadhaar":
            await self.request_aadhaar_number(update, context)
        elif data == "service_vehicle":
            await self.request_vehicle_number(update, context)
        elif data == "service_phone":
            await self.request_phone_number(update, context)
        elif data == "service_status":
            await self.show_status(update, context)
        elif data == "service_refer":
            await self.show_referral_info(update, context)
        elif data == "service_help":
            await self.show_help(update, context)
        elif data == "menu_back":
            await self.show_main_menu(update, context)
    
    async def request_aadhaar_number(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Request Aadhaar number input"""
        text = """
🆔 Aadhaar Lookup

Please enter the 12-digit Aadhaar number:

Example: 123456789012
        """
        
        keyboard = [[InlineKeyboardButton("🔙 Back to Menu", callback_data="menu_back")]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await update.callback_query.edit_message_text(text, reply_markup=reply_markup)
        
        # Set state to expect Aadhaar number
        context.user_data['expecting'] = 'aadhaar'
    
    async def request_vehicle_number(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Request vehicle number input"""
        text = """
🚗 Vehicle Lookup

Please enter the vehicle number:

Example: MH02FZ0555
        """
        
        keyboard = [[InlineKeyboardButton("🔙 Back to Menu", callback_data="menu_back")]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await update.callback_query.edit_message_text(text, reply_markup=reply_markup)
        
        # Set state to expect vehicle number
        context.user_data['expecting'] = 'vehicle'
    
    async def request_phone_number(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Request phone number input"""
        user_id = update.callback_query.from_user.id
        
        # Check credits and premium status
        self.cursor.execute(
            "SELECT premium_status, credits FROM users WHERE user_id = ?", 
            (user_id,)
        )
        user_data = self.cursor.fetchone()
        
        if not user_data:
            await update.callback_query.edit_message_text("❌ Please use /start first")
            return
        
        premium_status, credits = user_data
        
        text = f"""
📱 Pakistan Phone Lookup

Cost: {PHONE_LOOKUP_COST} credits per search
Your credits: {credits}

Please enter the Pakistan phone number:

Example: 3003658169
        """
        
        if credits < PHONE_LOOKUP_COST and not premium_status:
            text += f"\n\n❌ Not enough credits! You need {PHONE_LOOKUP_COST} credits.\nGet more credits via referrals or contact {CONTACT_USERNAME}"
        
        keyboard = [[InlineKeyboardButton("🔙 Back to Menu", callback_data="menu_back")]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await update.callback_query.edit_message_text(text, reply_markup=reply_markup)
        
        # Set state to expect phone number
        context.user_data['expecting'] = 'phone'
    
    async def show_status(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Show user status"""
        user_id = update.callback_query.from_user.id
        
        self.cursor.execute(
            "SELECT premium_status, premium_expiry, credits, referral_code FROM users WHERE user_id = ?", 
            (user_id,)
        )
        user_data = self.cursor.fetchone()
        
        if not user_data:
            await update.callback_query.edit_message_text("❌ Please use /start first")
            return
        
        premium_status, expiry, credits, referral_code = user_data
        
        if premium_status and expiry:
            time_left = expiry - datetime.now()
            hours_left = int(time_left.total_seconds() / 3600)
            days_left = int(hours_left / 24)
            
            if days_left > 0:
                expiry_text = f"{days_left} days {hours_left % 24} hours"
            else:
                expiry_text = f"{hours_left} hours"
            
            status_text = f"""
💎 **Premium Status:** ✅ ACTIVE
⏰ **Time Left:** {expiry_text}
📅 **Expiry Date:** {expiry.strftime('%Y-%m-%d %H:%M:%S')}
            """
        else:
            status_text = """
💎 **Premium Status:** ❌ INACTIVE
💎 Contact @Ronju360 to upgrade to premium.
            """
        
        text = f"""
📊 Your Status

{status_text}
💰 **Credits:** {credits}
📱 **Phone Lookup Cost:** {PHONE_LOOKUP_COST} credits
🔗 **Your Referral Code:** `{referral_code}`
        """
        
        keyboard = [
            [InlineKeyboardButton("👥 Refer & Earn", callback_data="service_refer")],
            [InlineKeyboardButton("🔙 Back to Menu", callback_data="menu_back")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await update.callback_query.edit_message_text(text, reply_markup=reply_markup)
    
    async def show_referral_info(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Show referral information"""
        user_id = update.callback_query.from_user.id
        
        self.cursor.execute(
            "SELECT referral_code FROM users WHERE user_id = ?", 
            (user_id,)
        )
        user_data = self.cursor.fetchone()
        
        if not user_data:
            await update.callback_query.edit_message_text("❌ Please use /start first")
            return
        
        referral_code = user_data[0]
        referral_link = f"https://t.me/{(await self.application.bot.get_me()).username}?start={referral_code}"
        
        # Count successful referrals
        self.cursor.execute(
            "SELECT COUNT(*) FROM referrals WHERE referrer_id = ? AND reward_claimed = TRUE",
            (user_id,)
        )
        referral_count = self.cursor.fetchone()[0]
        
        text = f"""
👥 Refer & Earn

🎁 Get {REFERRAL_CREDITS} credits for each friend who joins!

Your stats:
✅ Successful referrals: {referral_count}
💰 Credits earned: {referral_count * REFERRAL_CREDITS}

Share your referral link:
🔗 {referral_link}

Or share this code:
📝 `{referral_code}`
        """
        
        keyboard = [
            [InlineKeyboardButton("🔙 Back to Menu", callback_data="menu_back")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await update.callback_query.edit_message_text(text, reply_markup=reply_markup)
    
    async def show_help(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Show help information"""
        text = f"""
🆘 OSINT Bot Help

📊 Available Services:
• Aadhaar Information lookup
• Vehicle Information lookup  
• Pakistan Phone Information lookup

💎 Premium System:
• 24 hours free trial for new users
• After trial, contact {CONTACT_USERNAME} for premium

💰 Credit System:
• Pakistan phone lookups cost {PHONE_LOOKUP_COST} credits
• New users get {INITIAL_CREDITS} free credits
• Earn {REFERRAL_CREDITS} credits per referral

👥 Referral System:
Share your referral link to earn credits!

Need help? Contact: {CONTACT_USERNAME}
        """
        
        keyboard = [
            [InlineKeyboardButton("🔙 Back to Menu", callback_data="menu_back")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await update.callback_query.edit_message_text(text, reply_markup=reply_markup)
    
    async def handle_text_input(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle text input for various services"""
        user_id = update.effective_user.id
        text = update.message.text
        
        # Check what we're expecting
        expecting = context.user_data.get('expecting')
        
        if not expecting:
            await update.message.reply_text("Please use the menu buttons to select a service.")
            return
        
        if expecting == 'aadhaar':
            await self.process_aadhaar_lookup(update, context, text)
        elif expecting == 'vehicle':
            await self.process_vehicle_lookup(update, context, text)
        elif expecting == 'phone':
            await self.process_phone_lookup(update, context, text)
        
        # Clear expecting state
        context.user_data['expecting'] = None
    
    async def process_aadhaar_lookup(self, update: Update, context: ContextTypes.DEFAULT_TYPE, aadhaar_number: str):
        """Process Aadhaar lookup"""
        user_id = update.effective_user.id
        
        # Check force join
        self.cursor.execute("SELECT force_joined FROM users WHERE user_id = ?", (user_id,))
        user_data = self.cursor.fetchone()
        
        if not user_data or not user_data[0]:
            await update.message.reply_text("❌ Please verify joining our channel first using /start")
            return
        
        # Check premium status
        self.cursor.execute(
            "SELECT premium_status, premium_expiry FROM users WHERE user_id = ?", 
            (user_id,)
        )
        user_data = self.cursor.fetchone()
        
        if not user_data or not user_data[0]:
            await update.message.reply_text(
                "❌ Your premium access has expired.\n"
                f"💎 Contact {CONTACT_USERNAME} to upgrade to premium."
            )
            return
        
        # Validate Aadhaar number (basic check)
        aadhaar_number = aadhaar_number.strip()
        if not aadhaar_number.isdigit() or len(aadhaar_number) != 12:
            await update.message.reply_text("❌ Invalid Aadhaar number. Must be 12 digits.")
            return
        
        # Show loading message
        processing_msg = await update.message.reply_text("🔍 Fetching Aadhaar information...")
        
        try:
            # Call API
            api_url = f"{AADHAAR_API_BASE_URL}{aadhaar_number}"
            response = requests.get(api_url, timeout=30)
            
            if response.status_code == 200:
                data = response.json()
                
                # Check if it's the new format (ration card data)
                if 'memberDetailsList' in data:
                    # Format the response for ration card data
                    result_text = f"""
📄 **Ration Card Information Found**

🔢 **Aadhaar Number:** `{aadhaar_number}`
🏠 **Address:** {data.get('address', 'N/A')}
📍 **District:** {data.get('homeDistName', 'N/A')}
🏛️ **State:** {data.get('homeStateName', 'N/A')}
📋 **Scheme:** {data.get('schemeName', 'N/A')}
🆔 **RC ID:** {data.get('rcId', 'N/A')}

👥 **Family Members ({len(data['memberDetailsList'])}):**
"""
                    
                    # Add each family member
                    for member in data['memberDetailsList']:
                        result_text += f"• {member['memberName']} ({member['releationship_name']})\n"
                    
                    result_text += "\n⚠️ *This information is for authorized use only*"
                    
                else:
                    # Old format (direct Aadhaar data)
                    result_text = f"""
📄 **Aadhaar Information Found**

🔢 **Aadhaar Number:** `{aadhaar_number}`
📛 **Name:** {data.get('name', 'N/A')}
👤 **Gender:** {data.get('gender', 'N/A')}
📅 **Date of Birth:** {data.get('dob', 'N/A')}
📞 **Phone:** {data.get('phone', 'N/A')}
📧 **Email:** {data.get('email', 'N/A')}
🏠 **Address:** {data.get('address', 'N/A')}

⚠️ *This information is for authorized use only*
                    """
                
                await processing_msg.delete()
                
                # Split long messages (Telegram has 4096 character limit)
                if len(result_text) > 4096:
                    parts = [result_text[i:i+4096] for i in range(0, len(result_text), 4096)]
                    for part in parts:
                        await update.message.reply_text(part)
                else:
                    await update.message.reply_text(result_text)
                    
            else:
                await processing_msg.edit_text(f"❌ API Error: Status code {response.status_code}")
                
        except requests.exceptions.Timeout:
            await processing_msg.edit_text("⏰ Request timeout. Please try again.")
        except requests.exceptions.RequestException as e:
            await processing_msg.edit_text(f"❌ Network error: {str(e)}")
        except json.JSONDecodeError:
            await processing_msg.edit_text("❌ Invalid JSON response from API.")
        except Exception as e:
            logger.error(f"Aadhaar lookup error: {e}")
            await processing_msg.edit_text("❌ An error occurred. Please try again.")
        
        # Show menu again
        await self.show_main_menu(update, context)
    
    async def process_vehicle_lookup(self, update: Update, context: ContextTypes.DEFAULT_TYPE, vehicle_number: str):
        """Process Vehicle lookup"""
        user_id = update.effective_user.id
        
        # Check force join
        self.cursor.execute("SELECT force_joined FROM users WHERE user_id = ?", (user_id,))
        user_data = self.cursor.fetchone()
        
        if not user_data or not user_data[0]:
            await update.message.reply_text("❌ Please verify joining our channel first using /start")
            return
        
        # Check premium status
        self.cursor.execute(
            "SELECT premium_status, premium_expiry FROM users WHERE user_id = ?", 
            (user_id,)
        )
        user_data = self.cursor.fetchone()
        
        if not user_data or not user_data[0]:
            await update.message.reply_text(
                "❌ Your premium access has expired.\n"
                f"💎 Contact {CONTACT_USERNAME} to upgrade to premium."
            )
            return
        
        # Basic vehicle number validation
        vehicle_number = vehicle_number.upper().replace(' ', '')
        if len(vehicle_number) < 5:
            await update.message.reply_text("❌ Invalid Vehicle number.")
            return
        
        # Show loading message
        processing_msg = await update.message.reply_text("🚗 Fetching Vehicle information...")
        
        try:
            # Call Vehicle API
            api_url = f"{VEHICLE_API_BASE_URL}{vehicle_number}"
            response = requests.get(api_url, timeout=30)
            
            if response.status_code == 200:
                data = response.json()
                
                # Check if API returned success
                if data.get('status') == 'success':
                    # Format the vehicle information
                    result_text = f"""
🚗 **Vehicle Information Found**

🔢 **Vehicle Number:** `{data.get('vehicle_no', 'N/A')}`
👤 **Owner:** {data.get('owner', 'N/A')}
👨‍👦 **Father's Name:** {data.get('father_name', 'N/A')}
🏷️ **Owner Type:** {data.get('owner_serial_no', 'N/A')}
🚘 **Model:** {data.get('model', 'N/A')}
🏭 **Maker Model:** {data.get('maker_model', 'N/A')}
📊 **Vehicle Class:** {data.get('vehicle_class', 'N/A')}
⛽ **Fuel Type:** {data.get('fuel_type', 'N/A')}
🌿 **Fuel Norms:** {data.get('fuel_norms', 'N/A')}

🏢 **Insurance:**
   • Company: {data.get('insurance_company', 'N/A')}
   • Policy No: {data.get('insurance_no', 'N/A')}
   • Expiry: {data.get('insurance_upto', 'N/A')}
   • Status: {data.get('insurance_status', 'N/A')}

📅 **Other Details:**
   • Fitness Upto: {data.get('fitness_upto', 'N/A')}
   • Tax Upto: {data.get('tax_upto', 'N/A')}
   • PUC Upto: {data.get('puc_upto', 'N/A')}
   • PUC Status: {data.get('puc_status', 'N/A')}
   • Vehicle Age: {data.get('vehicle_age', 'N/A')}

🏠 **Address:** {data.get('address', 'N/A')}
📞 **Phone:** {data.get('phone', 'N/A')}
💳 **Financier:** {data.get('financier_name', 'N/A')}

⚠️ *This information is for authorized use only*
                    """
                else:
                    result_text = "❌ No vehicle information found for this number."
                
                await processing_msg.delete()
                
                # Split long messages
                if len(result_text) > 4096:
                    parts = [result_text[i:i+4096] for i in range(0, len(result_text), 4096)]
                    for part in parts:
                        await update.message.reply_text(part)
                else:
                    await update.message.reply_text(result_text)
                    
            else:
                await processing_msg.edit_text(f"❌ Vehicle API Error: Status code {response.status_code}")
                
        except requests.exceptions.Timeout:
            await processing_msg.edit_text("⏰ Request timeout. Please try again.")
        except requests.exceptions.RequestException as e:
            await processing_msg.edit_text(f"❌ Network error: {str(e)}")
        except json.JSONDecodeError:
            await processing_msg.edit_text("❌ Invalid JSON response from Vehicle API.")
        except Exception as e:
            logger.error(f"Vehicle lookup error: {e}")
            await processing_msg.edit_text("❌ An error occurred. Please try again.")
        
        # Show menu again
        await self.show_main_menu(update, context)
    
    async def process_phone_lookup(self, update: Update, context: ContextTypes.DEFAULT_TYPE, phone_number: str):
        """Process Pakistan Phone lookup"""
        user_id = update.effective_user.id
        
        # Check force join
        self.cursor.execute("SELECT force_joined FROM users WHERE user_id = ?", (user_id,))
        user_data = self.cursor.fetchone()
        
        if not user_data or not user_data[0]:
            await update.message.reply_text("❌ Please verify joining our channel first using /start")
            return
        
        # Check premium status and credits
        self.cursor.execute(
            "SELECT premium_status, premium_expiry, credits FROM users WHERE user_id = ?", 
            (user_id,)
        )
        user_data = self.cursor.fetchone()
        
        if not user_data:
            await update.message.reply_text("❌ Please use /start first")
            return
        
        premium_status, expiry, credits = user_data
        
        # Check if user has premium or enough credits
        if not premium_status and credits < PHONE_LOOKUP_COST:
            await update.message.reply_text(
                f"❌ Not enough credits! You need {PHONE_LOOKUP_COST} credits.\n"
                f"💰 Your credits: {credits}\n\n"
                f"Get more credits via referrals or contact {CONTACT_USERNAME}"
            )
            return
        
        # Basic phone number validation
        phone_number = phone_number.replace(' ', '').replace('+', '')
        if not phone_number.isdigit() or len(phone_number) < 8:
            await update.message.reply_text("❌ Invalid Phone number.")
            return
        
        # Deduct credits if not premium
        if not premium_status:
            self.cursor.execute(
                "UPDATE users SET credits = credits - ? WHERE user_id = ?",
                (PHONE_LOOKUP_COST, user_id)
            )
            self.conn.commit()
        
        # Show loading message
        processing_msg = await update.message.reply_text("📱 Fetching Phone information...")
        
        try:
            # Call Phone API
            api_url = f"{PAKISTAN_PHONE_API_BASE_URL}{phone_number}"
            response = requests.get(api_url, timeout=30)
            
            if response.status_code == 200:
                data = response.json()
                
                # Check if API returned success
                if data.get('success') and data.get('records'):
                    records = data['records']
                    
                    # Format the phone information
                    result_text = f"""
📱 **Pakistan Phone Information Found**

🔢 **Phone Number:** `{data.get('phone', phone_number)}`
📊 **Total Records Found:** {len(records)}
{'💳 **Credits deducted:** ' + str(PHONE_LOOKUP_COST) if not premium_status else '💎 **Premium user - No credits deducted**'}

📋 **Records:**
"""
                    
                    # Add each record
                    for i, record in enumerate(records, 1):
                        result_text += f"""
📞 **Record {i}:**
   • **Mobile:** {record.get('Mobile', 'N/A')}
   • **Name:** {record.get('Name', 'N/A')}
   • **CNIC:** {record.get('CNIC', 'N/A')}
   • **Address:** {record.get('Address', 'N/A')}
   • **Country:** {record.get('Country', 'N/A')}
"""
                    
                    result_text += "\n⚠️ *This information is for authorized use only*"
                    
                else:
                    result_text = f"❌ No phone information found for this number.\n{'💳 Credits were still deducted.' if not premium_status else ''}"
                
                await processing_msg.delete()
                
                # Split long messages
                if len(result_text) > 4096:
                    parts = [result_text[i:i+4096] for i in range(0, len(result_text), 4096)]
                    for part in parts:
                        await update.message.reply_text(part)
                else:
                    await update.message.reply_text(result_text)
                    
            else:
                await processing_msg.edit_text(f"❌ Phone API Error: Status code {response.status_code}")
                # Refund credits if error occurred
                if not premium_status:
                    self.cursor.execute(
                        "UPDATE users SET credits = credits + ? WHERE user_id = ?",
                        (PHONE_LOOKUP_COST, user_id)
                    )
                    self.conn.commit()
                
        except requests.exceptions.Timeout:
            await processing_msg.edit_text("⏰ Request timeout. Please try again.")
            # Refund credits if error occurred
            if not premium_status:
                self.cursor.execute(
                    "UPDATE users SET credits = credits + ? WHERE user_id = ?",
                    (PHONE_LOOKUP_COST, user_id)
                )
                self.conn.commit()
        except requests.exceptions.RequestException as e:
            await processing_msg.edit_text(f"❌ Network error: {str(e)}")
            # Refund credits if error occurred
            if not premium_status:
                self.cursor.execute(
                    "UPDATE users SET credits = credits + ? WHERE user_id = ?",
                    (PHONE_LOOKUP_COST, user_id)
                )
                self.conn.commit()
        except json.JSONDecodeError:
            await processing_msg.edit_text("❌ Invalid JSON response from Phone API.")
            # Refund credits if error occurred
            if not premium_status:
                self.cursor.execute(
                    "UPDATE users SET credits = credits + ? WHERE user_id = ?",
                    (PHONE_LOOKUP_COST, user_id)
                )
                self.conn.commit()
        except Exception as e:
            logger.error(f"Phone lookup error: {e}")
            await processing_msg.edit_text("❌ An error occurred. Please try again.")
            # Refund credits if error occurred
            if not premium_status:
                self.cursor.execute(
                    "UPDATE users SET credits = credits + ? WHERE user_id = ?",
                    (PHONE_LOOKUP_COST, user_id)
                )
                self.conn.commit()
        
        # Show menu again
        await self.show_main_menu(update, context)
    
    async def verify_join(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Verify channel join"""
        query = update.callback_query
        user_id = query.from_user.id
        
        try:
            # Check if user has joined the channel
            chat_member = await context.bot.get_chat_member(
                chat_id=FORCE_JOIN_CHANNEL, 
                user_id=user_id
            )
            
            if chat_member.status in ['member', 'administrator', 'creator']:
                # User has joined
                self.cursor.execute(
                    "UPDATE users SET force_joined = TRUE WHERE user_id = ?",
                    (user_id,)
                )
                self.conn.commit()
                
                await query.edit_message_text(
                    "✅ Verification successful! You can now use the bot."
                )
                
                # Send welcome message with menu
                await self.show_main_menu(update, context)
                
            else:
                await query.answer("❌ Please join the channel first!", show_alert=True)
                
        except Exception as e:
            logger.error(f"Error in verify_join: {e}")
            await query.answer("❌ Error verifying join. Please try again.", show_alert=True)
    
    # ... (Keep the existing premium_command, broadcast, stats methods as they are)
    # The admin commands remain the same
    
    async def premium_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle premium command - Admin only"""
        user_id = update.effective_user.id
        
        if user_id != ADMIN_USER_ID:
            await update.message.reply_text("❌ This command is for admin only.")
            return
        
        if not context.args:
            await update.message.reply_text("❌ Usage: /premium <user_id>")
            return
        
        try:
            target_user_id = int(context.args[0])
            expiry_time = datetime.now() + timedelta(days=30)
            
            self.cursor.execute(
                "UPDATE users SET premium_status = TRUE, premium_expiry = ? WHERE user_id = ?",
                (expiry_time, target_user_id)
            )
            
            if self.cursor.rowcount > 0:
                self.conn.commit()
                await update.message.reply_text(f"✅ Premium granted to user {target_user_id} for 30 days")
                
                # Notify user
                try:
                    await context.bot.send_message(
                        chat_id=target_user_id,
                        text="🎉 You have been granted 30 days premium access!\n\n"
                             "You can now use all features without restrictions."
                    )
                except:
                    pass
            else:
                await update.message.reply_text("❌ User not found")
                
        except ValueError:
            await update.message.reply_text("❌ Invalid user ID")
        except Exception as e:
            logger.error(f"Premium command error: {e}")
            await update.message.reply_text("❌ Error granting premium")
    
    async def add_credits(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Add credits to user - Admin only"""
        user_id = update.effective_user.id
        
        if user_id != ADMIN_USER_ID:
            await update.message.reply_text("❌ This command is for admin only.")
            return
        
        if len(context.args) < 2:
            await update.message.reply_text("❌ Usage: /addcredits <user_id> <amount>")
            return
        
        try:
            target_user_id = int(context.args[0])
            credit_amount = int(context.args[1])
            
            self.cursor.execute(
                "UPDATE users SET credits = credits + ? WHERE user_id = ?",
                (credit_amount, target_user_id)
            )
            
            if self.cursor.rowcount > 0:
                self.conn.commit()
                await update.message.reply_text(f"✅ Added {credit_amount} credits to user {target_user_id}")
                
                # Notify user
                try:
                    await context.bot.send_message(
                        chat_id=target_user_id,
                        text=f"🎉 You received {credit_amount} credits!\n\n"
                             f"Your total credits: {self.get_user_credits(target_user_id)}"
                    )
                except:
                    pass
            else:
                await update.message.reply_text("❌ User not found")
                
        except ValueError:
            await update.message.reply_text("❌ Invalid user ID or amount")
        except Exception as e:
            logger.error(f"Add credits error: {e}")
            await update.message.reply_text("❌ Error adding credits")
    
    def get_user_credits(self, user_id):
        """Get user's current credits"""
        self.cursor.execute("SELECT credits FROM users WHERE user_id = ?", (user_id,))
        result = self.cursor.fetchone()
        return result[0] if result else 0
    
    async def broadcast(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Broadcast message to all users - Admin only"""
        user_id = update.effective_user.id
        
        if user_id != ADMIN_USER_ID:
            await update.message.reply_text("❌ This command is for admin only.")
            return
        
        if not context.args:
            await update.message.reply_text("❌ Usage: /broadcast <message>")
            return
        
        broadcast_text = ' '.join(context.args)
        
        # Save broadcast text
        self.cursor.execute(
            "INSERT OR REPLACE INTO admin (id, broadcast_text) VALUES (1, ?)",
            (broadcast_text,)
        )
        self.conn.commit()
        
        # Get all users
        self.cursor.execute("SELECT user_id FROM users")
        users = self.cursor.fetchall()
        
        success_count = 0
        fail_count = 0
        
        processing_msg = await update.message.reply_text(f"📢 Broadcasting to {len(users)} users...")
        
        for user_id, in users:
            try:
                await context.bot.send_message(
                    chat_id=user_id,
                    text=f"📢 Announcement:\n\n{broadcast_text}"
                )
                success_count += 1
            except Exception as e:
                fail_count += 1
            
            # Small delay to avoid rate limits
            await asyncio.sleep(0.1)
        
        await processing_msg.edit_text(
            f"📊 Broadcast Complete:\n"
            f"✅ Success: {success_count}\n"
            f"❌ Failed: {fail_count}"
        )
    
    async def stats(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Show bot statistics - Admin only"""
        user_id = update.effective_user.id
        
        if user_id != ADMIN_USER_ID:
            await update.message.reply_text("❌ This command is for admin only.")
            return
        
        # Get stats
        self.cursor.execute("SELECT COUNT(*) FROM users")
        total_users = self.cursor.fetchone()[0]
        
        self.cursor.execute("SELECT COUNT(*) FROM users WHERE premium_status = 1")
        premium_users = self.cursor.fetchone()[0]
        
        self.cursor.execute("SELECT COUNT(*) FROM users WHERE force_joined = 1")
        verified_users = self.cursor.fetchone()[0]
        
        self.cursor.execute("SELECT COUNT(*) FROM referrals")
        total_referrals = self.cursor.fetchone()[0]
        
        stats_text = f"""
📊 **Bot Statistics**

👥 Total Users: {total_users}
💎 Premium Users: {premium_users}
✅ Verified Users: {verified_users}
👥 Total Referrals: {total_referrals}
🔗 Force Join Channel: {FORCE_JOIN_CHANNEL}
        """
        
        await update.message.reply_text(stats_text)
    
    async def handle_message(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle other messages"""
        # If user is expecting input, handle it
        if context.user_data.get('expecting'):
            await self.handle_text_input(update, context)
        else:
            await self.show_main_menu(update, context)
    
    def run(self):
        """Start the bot"""
        # Check if token is available
        if not BOT_TOKEN:
            logger.error("❌ BOT_TOKEN not found! Please set environment variable.")
            return
        
        self.application = Application.builder().token(BOT_TOKEN).build()
        
        # Add handlers
        self.application.add_handler(CommandHandler("start", self.start))
        self.application.add_handler(CommandHandler("premium", self.premium_command))
        self.application.add_handler(CommandHandler("addcredits", self.add_credits))
        self.application.add_handler(CommandHandler("broadcast", self.broadcast))
        self.application.add_handler(CommandHandler("stats", self.stats))
        self.application.add_handler(CallbackQueryHandler(self.handle_service_selection, pattern="^service_"))
        self.application.add_handler(CallbackQueryHandler(self.handle_service_selection, pattern="^menu_"))
        self.application.add_handler(CallbackQueryHandler(self.verify_join, pattern="^verify_join$"))
        self.application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, self.handle_message))
        
        # Start bot
        logger.info("Bot is starting...")
        self.application.run_polling()

if __name__ == '__main__':
    bot = OSINTBot()
    bot.run()