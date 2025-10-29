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

# Load environment variables
load_dotenv()

# Bot configuration - FIXED: Use environment variable properly
BOT_TOKEN = os.getenv('BOT_TOKEN', '7985992151:AAF64Ofq_-UeE84MoBF8CHNwUS1UrJeeLXc')
FORCE_JOIN_CHANNEL = "@ronjumodz"  # আপনার channel username দিয়ে change করুন
ADMIN_USER_ID = 7755338110  # আপনার user ID
API_BASE_URL = "https://happy-ration-info.vercel.app/fetch?key=paidchx&aadhaar="

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
                free_trial_used BOOLEAN DEFAULT FALSE
            )
        ''')
        
        # Create admin table
        self.cursor.execute('''
            CREATE TABLE IF NOT EXISTS admin (
                id INTEGER PRIMARY KEY,
                broadcast_text TEXT
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
                        text="❌ Your free access has expired. Contact @Ronju360 to upgrade to premium."
                    )
                except Exception as e:
                    logger.error(f"Could not send message to user {user_id}: {e}")
            
            self.conn.commit()
            logger.info(f"Checked premium expiry. {len(expired_users)} users expired")
        except Exception as e:
            logger.error(f"Error in check_premium_expiry: {e}")
    
    async def start(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /start command"""
        user_id = update.effective_user.id
        username = update.effective_user.username
        first_name = update.effective_user.first_name
        
        # Check if user exists
        self.cursor.execute("SELECT * FROM users WHERE user_id = ?", (user_id,))
        user = self.cursor.fetchone()
        
        if not user:
            # New user - give 24 hours premium
            expiry_time = datetime.now() + timedelta(hours=24)
            self.cursor.execute(
                "INSERT INTO users (user_id, username, first_name, premium_status, premium_expiry, free_trial_used) VALUES (?, ?, ?, ?, ?, ?)",
                (user_id, username, first_name, True, expiry_time, True)
            )
            self.conn.commit()
            
            welcome_text = f"""
👋 Welcome {first_name}!

🎁 You have received 24 hours FREE premium access!
⏰ Your free trial will expire in 24 hours.

📊 Use /aadhaar <Aadhaar Number> to fetch information

⚠️ Please join our channel first to verify yourself.
            """
        else:
            welcome_text = f"""
👋 Welcome back {first_name}!

📊 Use /aadhaar <Aadhaar Number> to fetch information

Check your premium status with /premium
            """
        
        # Check if user has joined channel
        self.cursor.execute("SELECT force_joined FROM users WHERE user_id = ?", (user_id,))
        user_data = self.cursor.fetchone()
        
        if user_data and user_data[0]:
            # User already verified
            await update.message.reply_text(welcome_text)
        else:
            # Ask to join channel - FIXED: URL generation
            keyboard = [
                [InlineKeyboardButton("✅ Verify Join", callback_data="verify_join")],
                [InlineKeyboardButton("🔗 Join Channel", url=f"https://t.me/{FORCE_JOIN_CHANNEL[1:]}")]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            await update.message.reply_text(
                f"{welcome_text}\n\n⚠️ Please join our channel and click verify:",
                reply_markup=reply_markup
            )
    
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
                    "✅ Verification successful! You can now use the bot.\n\n"
                    "Use /aadhaar <Aadhaar Number> to fetch information"
                )
                
                # Send welcome message
                await context.bot.send_message(
                    chat_id=user_id,
                    text="🎉 Welcome to OSINT Bot!\n\n"
                         "📊 You can now use Aadhaar lookup feature.\n"
                         "⏰ Remember: Free trial expires in 24 hours!"
                )
            else:
                await query.answer("❌ Please join the channel first!", show_alert=True)
                
        except Exception as e:
            logger.error(f"Error in verify_join: {e}")
            await query.answer("❌ Error verifying join. Please try again.", show_alert=True)
    
    async def aadhaar_lookup(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle Aadhaar lookup"""
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
                "💎 Contact @Ronju360 to upgrade to premium."
            )
            return
        
        # Check if aadhaar number provided
        if not context.args:
            await update.message.reply_text("❌ Please provide Aadhaar number\nUsage: /aadhaar 123456789012")
            return
        
        aadhaar_number = context.args[0]
        
        # Validate Aadhaar number (basic check)
        if not aadhaar_number.isdigit() or len(aadhaar_number) != 12:
            await update.message.reply_text("❌ Invalid Aadhaar number. Must be 12 digits.")
            return
        
        # Show loading message
        processing_msg = await update.message.reply_text("🔍 Fetching Aadhaar information...")
        
        try:
            # Call API
            api_url = f"{API_BASE_URL}{aadhaar_number}"
            response = requests.get(api_url, timeout=30)
            
            if response.status_code == 200:
                data = response.json()
                
                # Format the response
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
                await update.message.reply_text(result_text)
                
            else:
                await processing_msg.edit_text("❌ Error fetching data from API. Please try again.")
                
        except requests.exceptions.Timeout:
            await processing_msg.edit_text("⏰ Request timeout. Please try again.")
        except requests.exceptions.RequestException as e:
            await processing_msg.edit_text("❌ Network error. Please try again.")
        except json.JSONDecodeError:
            await processing_msg.edit_text("❌ Invalid response from API.")
        except Exception as e:
            logger.error(f"Aadhaar lookup error: {e}")
            await processing_msg.edit_text("❌ An error occurred. Please try again.")
    
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
        
        stats_text = f"""
📊 **Bot Statistics**

👥 Total Users: {total_users}
💎 Premium Users: {premium_users}
✅ Verified Users: {verified_users}
🔗 Force Join Channel: {FORCE_JOIN_CHANNEL}
        """
        
        await update.message.reply_text(stats_text)
    
    async def premium_status(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Show user's premium status"""
        user_id = update.effective_user.id
        
        self.cursor.execute(
            "SELECT premium_status, premium_expiry, free_trial_used FROM users WHERE user_id = ?", 
            (user_id,)
        )
        user_data = self.cursor.fetchone()
        
        if not user_data:
            await update.message.reply_text("❌ Please use /start first")
            return
        
        premium_status, expiry, free_trial_used = user_data
        
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
⏰ **Expires in:** {expiry_text}
📅 **Expiry date:** {expiry.strftime('%Y-%m-%d %H:%M:%S')}
            """
        else:
            if free_trial_used:
                status_text = """
💎 **Premium Status:** ❌ EXPIRED

⚠️ Your free access has expired.
💎 Contact @Ronju360 to upgrade to premium.
                """
            else:
                status_text = """
💎 **Premium Status:** ❌ INACTIVE

Use /start to activate your 24 hours free trial!
                """
        
        await update.message.reply_text(status_text)
    
    async def handle_message(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle other messages"""
        await update.message.reply_text(
            "🤖 OSINT Bot Help:\n\n"
            "/start - Start bot and get free trial\n"
            "/aadhaar <number> - Fetch Aadhaar information\n"
            "/premium_status - Check your premium status\n"
            "/help - Show this help message"
        )
    
    def run(self):
        """Start the bot"""
        # Check if token is available
        if not BOT_TOKEN:
            logger.error("❌ BOT_TOKEN not found! Please set environment variable.")
            return
        
        self.application = Application.builder().token(BOT_TOKEN).build()
        
        # Add handlers
        self.application.add_handler(CommandHandler("start", self.start))
        self.application.add_handler(CommandHandler("aadhaar", self.aadhaar_lookup))
        self.application.add_handler(CommandHandler("premium", self.premium_command))
        self.application.add_handler(CommandHandler("broadcast", self.broadcast))
        self.application.add_handler(CommandHandler("stats", self.stats))
        self.application.add_handler(CommandHandler("premium_status", self.premium_status))
        self.application.add_handler(CommandHandler("help", self.handle_message))
        self.application.add_handler(CallbackQueryHandler(self.verify_join, pattern="^verify_join$"))
        
        # Start bot
        logger.info("Bot is starting...")
        self.application.run_polling()

if __name__ == '__main__':
    bot = OSINTBot()
    bot.run()