from fastapi import FastAPI, APIRouter, HTTPException, Depends, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from dotenv import load_dotenv
from starlette.middleware.cors import CORSMiddleware
from motor.motor_asyncio import AsyncIOMotorClient
from pydantic import BaseModel, EmailStr, Field
from typing import List, Optional
from datetime import datetime, timedelta
from passlib.context import CryptContext
from jose import JWTError, jwt
from bson import ObjectId
import os
import logging
from pathlib import Path
import math
import httpx
import uuid
from contextlib import asynccontextmanager # <-- NUOVO IMPORT NECESSARIO

ROOT_DIR = Path(__file__).parent

# Caricamento sicuro del .env (non crasha se il file non esiste, es. su Render)
env_path = ROOT_DIR / '.env'
if env_path.exists():
    load_dotenv(env_path)

# Configure logging early
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# LLM Integration
from emergentintegrations.llm.chat import LlmChat, UserMessage

# ============ CONFIGURAZIONE SICURA MONGODB ============
# Usiamo .get() invece di [] per evitare il KeyError fatale se le variabili mancano.
# Inseriamo dei valori di fallback temporanei per permettere al modulo di caricarsi.
MONGO_URL = os.environ.get('MONGO_URL', 'mongodb://localhost:27017')
DB_NAME = os.environ.get('DB_NAME', 'egigo_db')

# Inizializzazione globale (permettere alle rotte di usare "db")
client = AsyncIOMotorClient(MONGO_URL)
db = client[DB_NAME]

# JWT Configuration
SECRET_KEY = os.environ.get("SECRET_KEY", "egigo_secret_key_change_in_production")
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_DAYS = 30

# LLM Configuration
EMERGENT_LLM_KEY = os.environ.get("EMERGENT_LLM_KEY", "")

# Password hashing
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
security = HTTPBearer()

# ============ LIFESPAN MANAGER ============
@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("🚀 Avvio del server in corso...")
    
    # Check preventivo delle variabili d'ambiente critiche
    missing_vars = []
    if not os.environ.get("MONGO_URL"): missing_vars.append("MONGO_URL")
    if not os.environ.get("DB_NAME"): missing_vars.append("DB_NAME")
    
    if missing_vars:
        logger.error(f"❌ CRITICAL: Mancano variabili d'ambiente: {', '.join(missing_vars)}")
        logger.error("👉 Configurale su Render in 'Environment Variables'.")
    
    # Test della connessione al database
    try:
        logger.info("⏳ Verifica connessione a MongoDB...")
        await client.admin.command('ping')
        logger.info("✅ Connessione a MongoDB stabilita con successo!")
    except Exception as e:
        logger.error(f"❌ Errore fatale di connessione a MongoDB (credenziali errate o IP non sbloccato su Atlas?): {e}")

    yield # Il server inizia ad accettare richieste qui
    
    # Chiusura pulita allo spegnimento
    logger.info("🛑 Spegnimento del server...")
    client.close()
    logger.info("✅ Connessione MongoDB chiusa correttamente.")

# Creiamo l'app iniettando il lifespan
app = FastAPI(lifespan=lifespan)


# Create a router with the /api prefix
api_router = APIRouter(prefix="/api")

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


# ============ PYDANTIC MODELS ============

class UserCreate(BaseModel):
    email: EmailStr
    password: str

class UserLogin(BaseModel):
    email: EmailStr
    password: str

class UserResponse(BaseModel):
    id: str
    email: str
    is_premium: bool = False
    name: str = ""

class TokenResponse(BaseModel):
    access_token: str
    token_type: str
    user_id: str
    is_premium: bool = False

class SpotCreate(BaseModel):
    titolo: str
    descrizione: str
    latitudine: float
    longitudine: float
    pubblico: bool = False  # Default: private spot

class SpotResponse(BaseModel):
    id: str
    user_id: str
    titolo: str
    descrizione: str
    latitudine: float
    longitudine: float
    pubblico: bool = False
    is_owner: bool = False  # Helps frontend know if user owns this spot
    created_at: datetime

class SpotUpdate(BaseModel):
    titolo: Optional[str] = None
    descrizione: Optional[str] = None
    latitudine: Optional[float] = None
    longitudine: Optional[float] = None
    pubblico: Optional[bool] = None

class CatchCreate(BaseModel):
    spot_id: str
    peso: float
    foto_base64: Optional[str] = None  # Photo is optional
    data_ora: datetime
    nome: Optional[str] = None  # Nome opzionale della cattura
    tipo_preda: str = "calamaro"  # calamaro, seppia
    # Environmental conditions at catch time
    wave_height: Optional[float] = None
    wind_kmh: Optional[float] = None
    temperature: Optional[float] = None
    moon_phase: Optional[str] = None
    moon_illumination: Optional[int] = None
    sea_condition: Optional[str] = None
    time_of_day: Optional[str] = None
    fishing_score: Optional[int] = None

class CatchUpdate(BaseModel):
    nome: Optional[str] = None
    peso: Optional[float] = None
    tipo_preda: Optional[str] = None
    spot_id: Optional[str] = None
    data_ora: Optional[datetime] = None
    ora_cattura: Optional[str] = None
    numero_pezzi: Optional[int] = None
    foto_base64: Optional[str] = None

class CatchResponse(BaseModel):
    id: str
    user_id: str
    spot_id: str
    peso: float
    foto_base64: Optional[str] = None  # Photo is optional
    data_ora: datetime
    tipo_preda: str
    nome: Optional[str] = None
    ora_cattura: Optional[str] = None
    numero_pezzi: Optional[int] = None
    created_at: datetime
    spot_titolo: Optional[str] = None
    # Environmental conditions
    wave_height: Optional[float] = None
    wind_kmh: Optional[float] = None
    temperature: Optional[float] = None
    moon_phase: Optional[str] = None
    moon_illumination: Optional[int] = None
    sea_condition: Optional[str] = None
    time_of_day: Optional[str] = None
    fishing_score: Optional[int] = None

class ConditionsResponse(BaseModel):
    punteggio_pesca: int
    condizione_mare: str
    vento_kmh: int
    fase_lunare: str
    percentuale_luna: int
    messaggio: str
    ora_corrente: int = 0

class WeatherResponse(BaseModel):
    temperature: float
    wind_speed: float
    wind_direction: float
    latitude: float
    longitude: float
    wave_height: Optional[float] = None
    sea_condition: Optional[str] = None
    sunrise: Optional[str] = None
    sunset: Optional[str] = None
    time_of_day: Optional[str] = None
    # NEW: Advanced environmental data
    water_temperature: Optional[float] = None  # Sea surface temperature
    wind_gusts: Optional[float] = None         # Wind gusts km/h


# ============ HELPER FUNCTIONS ============

def verify_password(plain_password: str, hashed_password: str) -> bool:
    return pwd_context.verify(plain_password, hashed_password)

def get_password_hash(password: str) -> str:
    return pwd_context.hash(password)

def create_access_token(data: dict) -> str:
    to_encode = data.copy()
    expire = datetime.utcnow() + timedelta(days=ACCESS_TOKEN_EXPIRE_DAYS)
    to_encode.update({"exp": expire})
    encoded_jwt = jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)
    return encoded_jwt

async def get_current_user(credentials: HTTPAuthorizationCredentials = Depends(security)) -> dict:
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Credenziali non valide",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        token = credentials.credentials
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        user_id: str = payload.get("sub")
        if user_id is None:
            raise credentials_exception
    except JWTError:
        raise credentials_exception
    
    user = await db.users.find_one({"_id": ObjectId(user_id)})
    if user is None:
        raise credentials_exception
    
    return user

def calculate_moon_phase() -> tuple:
    """Calculate current moon phase and illumination percentage using astronomical formula"""
    # Known new moon reference: January 6, 2000 at 18:14 UTC
    reference_new_moon = datetime(2000, 1, 6, 18, 14)
    lunar_cycle = 29.53058867  # synodic month in days
    
    now = datetime.utcnow()
    days_since_reference = (now - reference_new_moon).total_seconds() / 86400
    cycles = days_since_reference / lunar_cycle
    phase_fraction = cycles - math.floor(cycles)
    
    # Calculate illumination percentage using cosine formula
    # At new moon (0): 0%, at full moon (0.5): 100%
    illumination = int((1 - math.cos(phase_fraction * 2 * math.pi)) / 2 * 100)
    
    # Determine phase name in Italian based on phase fraction
    if phase_fraction < 0.0625 or phase_fraction >= 0.9375:
        fase = "Luna Nuova"
    elif 0.0625 <= phase_fraction < 0.1875:
        fase = "Luna Crescente"
    elif 0.1875 <= phase_fraction < 0.3125:
        fase = "Primo Quarto"
    elif 0.3125 <= phase_fraction < 0.4375:
        fase = "Gibbosa Crescente"
    elif 0.4375 <= phase_fraction < 0.5625:
        fase = "Luna Piena"
    elif 0.5625 <= phase_fraction < 0.6875:
        fase = "Gibbosa Calante"
    elif 0.6875 <= phase_fraction < 0.8125:
        fase = "Ultimo Quarto"
    else:
        fase = "Luna Calante"
    
    return fase, illumination

def calculate_fishing_score() -> dict:
    """Calculate realistic fishing score based on time and moon phase only.
    Weather data should come from the /api/weather endpoint separately.
    This endpoint provides a baseline score without real weather."""
    fase_lunare, percentuale_luna = calculate_moon_phase()
    
    # Get current time
    now = datetime.utcnow()
    current_hour = now.hour
    
    # Default weather values (will be overridden by frontend with real data)
    # Using moderate values as baseline
    vento_kmh = 15  # Default moderate wind
    
    # Determine sea condition based on wind (same thresholds as frontend)
    if vento_kmh <= 5:
        condizione_mare = "Calmo"
    elif vento_kmh <= 15:
        condizione_mare = "Poco Mosso"
    elif vento_kmh <= 25:
        condizione_mare = "Mosso"
    else:
        condizione_mare = "Molto Mosso"
    
    # Calculate score (0-100) based on realistic factors
    
    # 1. Moon phase score (35 points): Best at new moon (0-15%) and full moon (85-100%)
    if percentuale_luna <= 15 or percentuale_luna >= 85:
        moon_score = 35  # Optimal
    elif percentuale_luna <= 25 or percentuale_luna >= 75:
        moon_score = 28  # Very good
    elif percentuale_luna <= 35 or percentuale_luna >= 65:
        moon_score = 20  # Good
    else:
        moon_score = 12  # Moderate (quarter moon phases)
    
    # 2. Time of day score (35 points): Night fishing is best for squid
    # Dawn (5-7): Good (25 pts)
    # Day (8-17): Poor (8 pts)
    # Dusk (18-20): Excellent (35 pts)
    # Night (21-4): Excellent (35 pts)
    if 5 <= current_hour <= 7:
        time_score = 25  # Dawn - good
    elif 8 <= current_hour <= 17:
        time_score = 8  # Day - poor for eging
    elif 18 <= current_hour <= 20:
        time_score = 35  # Dusk - excellent
    else:  # 21-4
        time_score = 35  # Night - excellent
    
    # 3. Weather score (30 points): Using baseline moderate wind
    weather_score = 24  # Default for moderate wind (will be recalculated on frontend)
    
    punteggio_pesca = int(moon_score + time_score + weather_score)
    
    # Determine message based on score
    if punteggio_pesca >= 75:
        messaggio = "Condizioni ottime per l'eging"
    elif punteggio_pesca >= 55:
        messaggio = "Buone condizioni per l'eging"
    elif punteggio_pesca >= 35:
        messaggio = "Condizioni medie per l'eging"
    else:
        messaggio = "Condizioni scarse per l'eging"
    
    return {
        "punteggio_pesca": punteggio_pesca,
        "condizione_mare": condizione_mare,
        "vento_kmh": vento_kmh,
        "fase_lunare": fase_lunare,
        "percentuale_luna": percentuale_luna,
        "messaggio": messaggio,
        "ora_corrente": current_hour
    }


# ============ AUTH ROUTES ============

@api_router.post("/auth/register", response_model=TokenResponse)
async def register(user_data: UserCreate):
    # Check if user already exists
    existing_user = await db.users.find_one({"email": user_data.email})
    if existing_user:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Email già registrata"
        )
    
    # Create new user with is_premium field
    hashed_password = get_password_hash(user_data.password)
    new_user = {
        "email": user_data.email,
        "password_hash": hashed_password,
        "is_premium": False,  # New users start as free
        "created_at": datetime.utcnow()
    }
    
    result = await db.users.insert_one(new_user)
    user_id = str(result.inserted_id)
    
    # Create access token
    access_token = create_access_token(data={"sub": user_id})
    
    return TokenResponse(
        access_token=access_token,
        token_type="bearer",
        user_id=user_id,
        is_premium=False
    )

@api_router.post("/auth/login", response_model=TokenResponse)
async def login(user_data: UserLogin):
    # Find user
    user = await db.users.find_one({"email": user_data.email})
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Email o password non corretti"
        )
    
    # Verify password
    if not verify_password(user_data.password, user["password_hash"]):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Email o password non corretti"
        )
    
    # Create access token
    user_id = str(user["_id"])
    is_premium = user.get("is_premium", False)
    access_token = create_access_token(data={"sub": user_id})
    
    return TokenResponse(
        access_token=access_token,
        token_type="bearer",
        user_id=user_id,
        is_premium=is_premium
    )

@api_router.get("/auth/me", response_model=UserResponse)
async def get_me(current_user: dict = Depends(get_current_user)):
    return UserResponse(
        id=str(current_user["_id"]),
        email=current_user["email"],
        is_premium=current_user.get("is_premium", False),
        name=current_user.get("name", "")
    )


# ============ USER PROFILE ROUTES ============

class UserUpdateRequest(BaseModel):
    email: Optional[EmailStr] = None
    name: Optional[str] = None

class PasswordChangeRequest(BaseModel):
    current_password: str
    new_password: str

@api_router.put("/user/update")
async def update_user_profile(
    update_data: UserUpdateRequest,
    current_user: dict = Depends(get_current_user)
):
    """Update user profile (email and/or name)"""
    updates = {}
    
    # Validate and prepare email update
    if update_data.email and update_data.email != current_user["email"]:
        # Check if email is already taken
        existing = await db.users.find_one({"email": update_data.email})
        if existing:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Email già in uso da un altro utente"
            )
        updates["email"] = update_data.email
    
    # Prepare name update
    if update_data.name is not None:
        updates["name"] = update_data.name.strip()
    
    if not updates:
        return {"success": True, "message": "Nessuna modifica"}
    
    # Update user
    await db.users.update_one(
        {"_id": current_user["_id"]},
        {"$set": updates}
    )
    
    return {
        "success": True,
        "message": "Profilo aggiornato con successo",
        "updated_fields": list(updates.keys())
    }

@api_router.post("/user/change-password")
async def change_password(
    password_data: PasswordChangeRequest,
    current_user: dict = Depends(get_current_user)
):
    """Change user password"""
    # Verify current password
    if not verify_password(password_data.current_password, current_user["password_hash"]):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Password attuale non corretta"
        )
    
    # Validate new password
    if len(password_data.new_password) < 6:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="La nuova password deve avere almeno 6 caratteri"
        )
    
    if password_data.new_password == password_data.current_password:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="La nuova password deve essere diversa dalla precedente"
        )
    
    # Hash and save new password
    new_hash = get_password_hash(password_data.new_password)
    await db.users.update_one(
        {"_id": current_user["_id"]},
        {"$set": {"password_hash": new_hash}}
    )
    
    return {
        "success": True,
        "message": "Password modificata con successo"
    }


@api_router.post("/auth/reset-password")
async def reset_password(email: EmailStr):
    """
    Simulated password reset for MVP
    In production, this would send an email with reset link
    """
    # Check if user exists (but don't reveal this info for security)
    user = await db.users.find_one({"email": email})
    
    # Always return success message for security (prevent email enumeration)
    return {
        "success": True,
        "message": "Se l'email è registrata, riceverai un link per reimpostare la password"
    }


# ============ PREMIUM ROUTES ============

@api_router.post("/premium/activate")
async def activate_premium(current_user: dict = Depends(get_current_user)):
    """Activate premium for current user (MVP - no payment)"""
    await db.users.update_one(
        {"_id": current_user["_id"]},
        {"$set": {"is_premium": True}}
    )
    return {
        "success": True,
        "message": "Premium attivato con successo!",
        "is_premium": True
    }

@api_router.get("/premium/status")
async def get_premium_status(current_user: dict = Depends(get_current_user)):
    """Get current premium status"""
    return {
        "is_premium": current_user.get("is_premium", False)
    }


# ============ FORECAST ROUTES (PREMIUM) ============

class ForecastSlot(BaseModel):
    data: str  # Date string
    ora: str
    punteggio: int
    etichetta: str
    vento_kmh: float
    wave_height: float
    condizione_mare: str
    temperatura: float = 0

class DayForecast(BaseModel):
    data: str
    giorno: str  # Mon, Tue, etc in Italian
    slots: List[ForecastSlot]
    punteggio_medio: int
    migliore_slot: str

class ForecastResponse(BaseModel):
    giorni: List[DayForecast]
    miglior_giorno: str
    miglior_orario: str
    punteggio_migliore: int
    fase_lunare: str

# ============ UNIFIED SCORE OVERRIDE RULES ============
# These MUST mirror the logic in frontend/services/unifiedScoreService.ts
# This ensures consistent scoring across the entire app

def apply_score_overrides(base_score: int, sea_condition: str, wave_height: float, wind_kmh: float, time_phase: str) -> dict:
    """
    Apply override rules to the base score.
    MIRRORS: frontend/services/unifiedScoreService.ts -> applyScoreOverrides()
    
    RULES (applied in order of priority):
    1. HARD LIMIT: sea="Molto mosso" OR wave_height > 1.0 → score=10
    2. HIGH WAVES: wave > 0.8 → score = base * 0.4 (indipendente dal vento - risacca)
    3. STRONG WIND: wind > 25 → score = base * 0.3
    4. COMBINED BAD: wave > 0.6 AND wind > 18 → score = base * 0.5
    5. GOOD CONDITIONS BONUS: wave < 0.4 AND wind < 10 AND (sunset/night) → score += 5
    6. NORMAL: no critical conditions → score = base
    """
    sea_lower = sea_condition.lower()
    effective_wave = wave_height if wave_height is not None else 0
    
    # RULE 1: HARD LIMIT - Sea priority (most critical)
    if sea_lower == 'molto mosso' or effective_wave > 1.0:
        return {
            'final_score': 10,
            'was_overridden': True,
            'override_reason': f'Mare troppo mosso! Onde {effective_wave:.1f}m' if effective_wave > 1.0 else 'Mare molto mosso!',
            'multiplier': None,
            'bonus': 0
        }
    
    # RULE 2: HIGH WAVES - INDIPENDENTE DAL VENTO
    # wave > 0.8m → score = base * 0.4 (la risacca rovina l'azione di pesca)
    if effective_wave > 0.8:
        penalized_score = max(15, round(base_score * 0.4))
        return {
            'final_score': penalized_score,
            'was_overridden': True,
            'override_reason': f'Onde {effective_wave:.1f}m - Risacca disturba la pesca',
            'multiplier': 0.4,
            'bonus': 0
        }
    
    # RULE 3: STRONG WIND - wind > 25 km/h → score = base * 0.3
    if wind_kmh > 25:
        penalized_score = max(5, round(base_score * 0.3))
        return {
            'final_score': penalized_score,
            'was_overridden': True,
            'override_reason': f'Vento molto forte ({wind_kmh} km/h)',
            'multiplier': 0.3,
            'bonus': 0
        }
    
    # RULE 4: COMBINED BAD CONDITIONS - wave > 0.6 AND wind > 18
    if effective_wave > 0.6 and wind_kmh > 18:
        penalized_score = max(10, round(base_score * 0.5))
        return {
            'final_score': penalized_score,
            'was_overridden': True,
            'override_reason': f'Onde {effective_wave:.1f}m + vento {wind_kmh} km/h',
            'multiplier': 0.5,
            'bonus': 0
        }
    
    # RULE 5: GOOD CONDITIONS BONUS
    # wave < 0.4 AND wind < 10 AND (sunset OR night) → score += 5
    is_good_time = time_phase.lower() in ['tramonto', 'notte', 'crepuscolo_serale', 'crepuscolo_mattutino']
    if effective_wave < 0.4 and wind_kmh < 10 and is_good_time:
        bonus_score = min(100, base_score + 5)
        return {
            'final_score': bonus_score,
            'was_overridden': False,
            'override_reason': None,
            'multiplier': None,
            'bonus': 5
        }
    
    # RULE 6: NORMAL CASE
    return {
        'final_score': base_score,
        'was_overridden': False,
        'override_reason': None,
        'multiplier': None,
        'bonus': 0
    }


def get_aligned_score_label(score: int, sea_condition: str, wave_height: float) -> str:
    """
    Get the correct label based on final score AND conditions.
    MIRRORS: frontend/services/unifiedScoreService.ts -> getAlignedScoreLabel()
    
    CRITICAL: If sea is bad, status MUST be "Scarse" regardless of score
    """
    sea_lower = sea_condition.lower()
    effective_wave = wave_height if wave_height is not None else 0
    
    # CRITICAL: If sea is bad, status MUST be "Scarse" regardless of score
    if sea_lower == 'molto mosso' or effective_wave > 1.0:
        return 'Scarse'
    
    # For high waves (> 0.8m), cap at "Medie" - risacca disturba pesca
    if effective_wave > 0.8:
        if score >= 30:
            return 'Medie'
        return 'Scarse'
    
    # For moderate waves (> 0.6m), cap at "Buone"
    if sea_lower == 'mosso' or effective_wave > 0.6:
        if score >= 50:
            return 'Buone'
        if score >= 30:
            return 'Medie'
        return 'Scarse'
    
    # Normal label assignment
    if score >= 85:
        return 'Eccellenti'
    if score >= 70:
        return 'Ottime'
    if score >= 50:
        return 'Buone'
    if score >= 30:
        return 'Medie'
    return 'Scarse'


def get_time_phase_from_hour(hour: int) -> str:
    """Get time phase name from hour for override rules"""
    if 5 <= hour <= 7:
        return 'alba'
    elif 8 <= hour <= 17:
        return 'giorno'
    elif 18 <= hour <= 20:
        return 'tramonto'
    else:  # 21-4
        return 'notte'


@api_router.get("/forecast-hourly")
async def get_hourly_forecast_data(lat: float = 43.55, lon: float = 10.31):
    """
    Get 5-day HOURLY weather data (24h per day) for premium Forecast screen.
    Returns complete hourly data for each day to enable detailed graphs and analysis.
    Frontend uses unifiedScoreService for score calculation.
    """
    try:
        import httpx
        from datetime import timedelta
        
        # Fetch 5-day hourly weather data from Open-Meteo
        weather_url = f"https://api.open-meteo.com/v1/forecast?latitude={lat}&longitude={lon}&hourly=wind_speed_10m,wind_gusts_10m,wind_direction_10m,temperature_2m,relative_humidity_2m,precipitation,pressure_msl&daily=sunrise,sunset&forecast_days=5&timezone=Europe/Rome"
        marine_url = f"https://marine-api.open-meteo.com/v1/marine?latitude={lat}&longitude={lon}&hourly=wave_height,wave_direction,wave_period,sea_surface_temperature&forecast_days=5&timezone=Europe/Rome"
        
        async with httpx.AsyncClient() as client:
            weather_resp = await client.get(weather_url, timeout=15.0)
            marine_resp = await client.get(marine_url, timeout=15.0)
        
        weather_data = weather_resp.json()
        marine_data = marine_resp.json()
        
        # Get moon data
        fase_lunare, percentuale_luna = calculate_moon_phase()
        
        # Italian day names
        giorni_it = ['Lun', 'Mar', 'Mer', 'Gio', 'Ven', 'Sab', 'Dom']
        
        giorni = []
        
        # Process 5 days with FULL 24-hour data
        for day_offset in range(5):
            day_date = datetime.now() + timedelta(days=day_offset)
            data_str = day_date.strftime("%Y-%m-%d")
            giorno_nome = giorni_it[day_date.weekday()]
            
            # Get sunrise/sunset for this day
            sunrise = None
            sunset = None
            if "daily" in weather_data and day_offset < len(weather_data["daily"]["sunrise"]):
                sunrise = weather_data["daily"]["sunrise"][day_offset]
                sunset = weather_data["daily"]["sunset"][day_offset]
            
            day_slots = []
            
            # Process ALL 24 hours for this day
            for hour in range(24):
                hour_index = day_offset * 24 + hour
                
                # Safely get weather values with defaults
                wind_kmh = 10.0
                wind_gusts = None
                wind_direction = 0
                wave_height = 0.5
                wave_direction = None
                wave_period = None
                water_temperature = None
                temperatura = 15.0
                humidity = 70
                precipitation = 0.0
                pressure = 1015.0
                
                if "hourly" in weather_data:
                    hourly = weather_data["hourly"]
                    if hour_index < len(hourly.get("wind_speed_10m", [])):
                        wind_kmh = hourly["wind_speed_10m"][hour_index] or 10.0
                    if hour_index < len(hourly.get("wind_gusts_10m", [])):
                        wind_gusts = hourly["wind_gusts_10m"][hour_index]
                    if hour_index < len(hourly.get("wind_direction_10m", [])):
                        wind_direction = hourly["wind_direction_10m"][hour_index] or 0
                    if hour_index < len(hourly.get("temperature_2m", [])):
                        temperatura = hourly["temperature_2m"][hour_index] or 15.0
                    if hour_index < len(hourly.get("relative_humidity_2m", [])):
                        humidity = hourly["relative_humidity_2m"][hour_index] or 70
                    if hour_index < len(hourly.get("precipitation", [])):
                        precipitation = hourly["precipitation"][hour_index] or 0.0
                    if hour_index < len(hourly.get("pressure_msl", [])):
                        pressure = hourly["pressure_msl"][hour_index] or 1015.0
                
                if "hourly" in marine_data:
                    marine_hourly = marine_data["hourly"]
                    if hour_index < len(marine_hourly.get("wave_height", [])):
                        wh = marine_hourly["wave_height"][hour_index]
                        wave_height = wh if wh is not None else 0.5
                    if hour_index < len(marine_hourly.get("wave_direction", [])):
                        wave_direction = marine_hourly["wave_direction"][hour_index]
                    if hour_index < len(marine_hourly.get("wave_period", [])):
                        wave_period = marine_hourly["wave_period"][hour_index]
                    if hour_index < len(marine_hourly.get("sea_surface_temperature", [])):
                        water_temperature = marine_hourly["sea_surface_temperature"][hour_index]
                
                # Determine sea condition
                if wave_height <= 0.2:
                    condizione_mare = "Piatto"
                elif wave_height <= 0.5:
                    condizione_mare = "Calmo"
                elif wave_height <= 0.8:
                    condizione_mare = "Poco Mosso"
                elif wave_height <= 1.2:
                    condizione_mare = "Mosso"
                else:
                    condizione_mare = "Molto Mosso"
                
                # Build slot timestamp
                slot_datetime = day_date.replace(hour=hour, minute=0, second=0, microsecond=0)
                ora = f"{hour:02d}:00"
                
                day_slots.append({
                    "data": data_str,
                    "ora": ora,
                    "timestamp": slot_datetime.isoformat(),
                    # Weather data
                    "vento_kmh": round(wind_kmh, 1),
                    "wind_gusts": round(wind_gusts, 1) if wind_gusts else None,
                    "wind_direction": round(wind_direction) if wind_direction else None,
                    "wave_height": round(wave_height, 2),
                    "wave_direction": round(wave_direction) if wave_direction else None,
                    "wave_period": round(wave_period, 1) if wave_period else None,
                    "water_temperature": round(water_temperature, 1) if water_temperature else None,
                    "temperatura": round(temperatura, 1),
                    "humidity": round(humidity),
                    "precipitation": round(precipitation, 1),
                    "pressure": round(pressure, 1),
                    "condizione_mare": condizione_mare,
                    "sunrise": sunrise,
                    "sunset": sunset,
                })
            
            giorni.append({
                "data": data_str,
                "giorno": f"{giorno_nome} {day_date.strftime('%d/%m')}",
                "slots": day_slots,
                "sunrise": sunrise,
                "sunset": sunset,
            })
        
        return {
            "giorni": giorni,
            "fase_lunare": fase_lunare,
            "percentuale_luna": percentuale_luna,
        }
        
    except Exception as e:
        logger.error(f"Hourly forecast error: {e}")
        return {
            "giorni": [],
            "fase_lunare": "N/D",
            "percentuale_luna": 0,
            "error": str(e)
        }


@api_router.get("/forecast-data")
async def get_5day_forecast_data(lat: float = 43.55, lon: float = 10.31):
    """
    Get 5-day RAW WEATHER DATA for frontend to calculate scores using unifiedScoreService.
    This endpoint provides only the data needed for frontend score calculation.
    
    IMPORTANT: Frontend MUST use unifiedScoreService to calculate scores from this data.
    This ensures SINGLE SOURCE OF TRUTH - same logic as Home and Egi Advisor.
    """
    try:
        import httpx
        from datetime import timedelta
        
        # Fetch 5-day hourly weather data from Open-Meteo
        # Include sunrise/sunset for accurate time phase calculation
        weather_url = f"https://api.open-meteo.com/v1/forecast?latitude={lat}&longitude={lon}&hourly=wind_speed_10m,wind_gusts_10m,wind_direction_10m,temperature_2m&daily=sunrise,sunset&forecast_days=5&timezone=Europe/Rome"
        marine_url = f"https://marine-api.open-meteo.com/v1/marine?latitude={lat}&longitude={lon}&hourly=wave_height,sea_surface_temperature&forecast_days=5&timezone=Europe/Rome"
        
        async with httpx.AsyncClient() as client:
            weather_resp = await client.get(weather_url, timeout=15.0)
            marine_resp = await client.get(marine_url, timeout=15.0)
        
        weather_data = weather_resp.json()
        marine_data = marine_resp.json()
        
        # Get moon data
        fase_lunare, percentuale_luna = calculate_moon_phase()
        
        # Italian day names
        giorni_it = ['Lun', 'Mar', 'Mer', 'Gio', 'Ven', 'Sab', 'Dom']
        
        giorni = []
        
        # Process 5 days - return RAW data for each slot
        for day_offset in range(5):
            day_date = datetime.now() + timedelta(days=day_offset)
            data_str = day_date.strftime("%Y-%m-%d")
            giorno_nome = giorni_it[day_date.weekday()]
            
            # Get sunrise/sunset for this day
            sunrise = None
            sunset = None
            if "daily" in weather_data and day_offset < len(weather_data["daily"]["sunrise"]):
                sunrise = weather_data["daily"]["sunrise"][day_offset]
                sunset = weather_data["daily"]["sunset"][day_offset]
            
            day_slots = []
            
            # 6 slots per day: 06:00, 10:00, 14:00, 18:00, 21:00, 00:00
            slot_hours = [6, 10, 14, 18, 21, 0]
            
            for slot_hour in slot_hours:
                # Calculate index in hourly data (day_offset * 24 + hour)
                hour_index = day_offset * 24 + slot_hour
                if slot_hour == 0 and day_offset < 4:  # Midnight belongs to next day
                    hour_index = (day_offset + 1) * 24
                
                # Safely get weather values with defaults
                wind_kmh = 15.0
                wind_gusts = None
                wave_height = 0.5
                water_temperature = None
                temperatura = 15.0
                
                if "hourly" in weather_data:
                    hourly = weather_data["hourly"]
                    if hour_index < len(hourly.get("wind_speed_10m", [])):
                        wind_kmh = hourly["wind_speed_10m"][hour_index] or 15.0
                    if hour_index < len(hourly.get("wind_gusts_10m", [])):
                        wind_gusts = hourly["wind_gusts_10m"][hour_index]
                    if hour_index < len(hourly.get("temperature_2m", [])):
                        temperatura = hourly["temperature_2m"][hour_index] or 15.0
                
                if "hourly" in marine_data:
                    marine_hourly = marine_data["hourly"]
                    if hour_index < len(marine_hourly.get("wave_height", [])):
                        wh = marine_hourly["wave_height"][hour_index]
                        wave_height = wh if wh is not None else 0.5
                    if hour_index < len(marine_hourly.get("sea_surface_temperature", [])):
                        water_temperature = marine_hourly["sea_surface_temperature"][hour_index]
                
                # Determine sea condition (same logic as frontend getSeaCondition)
                # UPDATED THRESHOLDS for more realistic scoring
                if wave_height <= 0.2:
                    condizione_mare = "Piatto"
                elif wave_height <= 0.5:
                    condizione_mare = "Calmo"
                elif wave_height <= 0.8:
                    condizione_mare = "Poco Mosso"
                elif wave_height <= 1.2:
                    condizione_mare = "Mosso"
                else:
                    condizione_mare = "Molto Mosso"
                
                # Build slot timestamp for frontend
                slot_datetime = day_date.replace(hour=slot_hour, minute=0, second=0, microsecond=0)
                if slot_hour == 0 and day_offset < 4:
                    slot_datetime = (day_date + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
                
                # Format time
                ora = f"{slot_hour:02d}:00"
                
                day_slots.append({
                    "data": data_str,
                    "ora": ora,
                    "timestamp": slot_datetime.isoformat(),
                    # RAW weather data for frontend unifiedScoreService
                    "vento_kmh": round(wind_kmh, 1),
                    "wind_gusts": round(wind_gusts, 1) if wind_gusts else None,
                    "wave_height": round(wave_height, 2),
                    "water_temperature": round(water_temperature, 1) if water_temperature else None,
                    "temperatura": round(temperatura, 1),
                    "condizione_mare": condizione_mare,
                    "sunrise": sunrise,
                    "sunset": sunset,
                })
            
            giorni.append({
                "data": data_str,
                "giorno": f"{giorno_nome} {day_date.strftime('%d/%m')}",
                "slots": day_slots,
                "sunrise": sunrise,
                "sunset": sunset,
            })
        
        return {
            "giorni": giorni,
            "fase_lunare": fase_lunare,
            "percentuale_luna": percentuale_luna,
            # Note: miglior_giorno, miglior_orario, punteggio_migliore 
            # will be calculated by frontend using unifiedScoreService
        }
        
    except Exception as e:
        logger.error(f"Forecast data error: {e}")
        return {
            "giorni": [],
            "fase_lunare": "N/D",
            "percentuale_luna": 0,
            "error": str(e)
        }


@api_router.get("/forecast", response_model=ForecastResponse)
async def get_5day_forecast(lat: float = 43.55, lon: float = 10.31):
    """
    DEPRECATED: Use /forecast-data and calculate scores in frontend with unifiedScoreService.
    
    This endpoint is kept for backward compatibility but the scores may differ
    from Home/Egi because it duplicates the scoring logic.
    
    For consistent scoring, frontend should use /forecast-data endpoint.
    """
    try:
        import httpx
        from datetime import timedelta
        
        # Fetch 5-day hourly weather data from Open-Meteo
        weather_url = f"https://api.open-meteo.com/v1/forecast?latitude={lat}&longitude={lon}&hourly=wind_speed_10m,wind_direction_10m,temperature_2m&forecast_days=5&timezone=Europe/Rome"
        marine_url = f"https://marine-api.open-meteo.com/v1/marine?latitude={lat}&longitude={lon}&hourly=wave_height&forecast_days=5&timezone=Europe/Rome"
        
        async with httpx.AsyncClient() as client:
            weather_resp = await client.get(weather_url, timeout=15.0)
            marine_resp = await client.get(marine_url, timeout=15.0)
        
        weather_data = weather_resp.json()
        marine_data = marine_resp.json()
        
        # Get moon phase
        fase_lunare, percentuale_luna = calculate_moon_phase()
        
        # Calculate moon score (MIRRORS unifiedScoreService: max 15 points)
        if percentuale_luna <= 10 or percentuale_luna >= 90:
            moon_score = 15
        elif percentuale_luna <= 25 or percentuale_luna >= 75:
            moon_score = 12
        elif percentuale_luna <= 35 or percentuale_luna >= 65:
            moon_score = 8
        else:
            moon_score = 6
        
        # Italian day names
        giorni_it = ['Lun', 'Mar', 'Mer', 'Gio', 'Ven', 'Sab', 'Dom']
        
        giorni = []
        best_overall_score = 0
        best_overall_day = ""
        best_overall_time = ""
        
        # Process 5 days
        for day_offset in range(5):
            day_date = datetime.now() + timedelta(days=day_offset)
            data_str = day_date.strftime("%Y-%m-%d")
            giorno_nome = giorni_it[day_date.weekday()]
            
            day_slots = []
            day_best_score = 0
            day_best_time = ""
            
            # 6 slots per day: 06:00, 10:00, 14:00, 18:00, 21:00, 00:00
            slot_hours = [6, 10, 14, 18, 21, 0]
            
            for slot_hour in slot_hours:
                # Calculate index in hourly data (day_offset * 24 + hour)
                hour_index = day_offset * 24 + slot_hour
                if slot_hour == 0 and day_offset < 4:  # Midnight belongs to next day
                    hour_index = (day_offset + 1) * 24
                
                # Safely get weather values
                wind_kmh = 15.0
                wave_height = 0.5
                temperatura = 15.0
                
                if "hourly" in weather_data and hour_index < len(weather_data["hourly"]["wind_speed_10m"]):
                    wind_kmh = weather_data["hourly"]["wind_speed_10m"][hour_index]
                    temperatura = weather_data["hourly"]["temperature_2m"][hour_index]
                
                if "hourly" in marine_data and hour_index < len(marine_data["hourly"]["wave_height"]):
                    wh = marine_data["hourly"]["wave_height"][hour_index]
                    wave_height = wh if wh is not None else 0.5
                
                # Determine sea condition (MIRRORS unifiedScoreService: getSeaCondition)
                # UPDATED THRESHOLDS for more realistic scoring
                if wave_height <= 0.2:
                    condizione_mare = "Piatto"
                elif wave_height <= 0.5:
                    condizione_mare = "Calmo"
                elif wave_height <= 0.8:
                    condizione_mare = "Poco Mosso"
                elif wave_height <= 1.2:
                    condizione_mare = "Mosso"
                else:
                    condizione_mare = "Molto Mosso"
                
                # Get time phase for override rules
                time_phase = get_time_phase_from_hour(slot_hour)
                
                # Calculate SEA score (MIRRORS unifiedScoreService: max 35 points)
                if condizione_mare.lower() == 'piatto':
                    sea_score = 35
                elif condizione_mare.lower() == 'calmo':
                    sea_score = 30
                elif condizione_mare.lower() == 'poco mosso':
                    sea_score = 20
                elif condizione_mare.lower() == 'mosso':
                    sea_score = 8
                else:  # molto mosso
                    sea_score = 0
                
                # Calculate WIND score (MIRRORS unifiedScoreService: max 20 points)
                if wind_kmh <= 8:
                    wind_score = 20
                elif wind_kmh <= 15:
                    wind_score = 16
                elif wind_kmh <= 22:
                    wind_score = 12
                elif wind_kmh <= 30:
                    wind_score = 6
                else:
                    wind_score = 0
                
                # Calculate TIME score (MIRRORS unifiedScoreService: max 25 points)
                if slot_hour in [18, 19, 20]:  # tramonto/crepuscolo
                    time_score = 25
                elif slot_hour in [6, 7]:  # alba
                    time_score = 22
                elif slot_hour in [21, 22, 23, 0, 1, 2, 3, 4]:  # notte
                    time_score = 18
                else:  # giorno (8-17)
                    time_score = 5
                
                # Calculate TEMPERATURE score (MIRRORS unifiedScoreService: max 5 points)
                # Using air temp as proxy since we don't have water temp in forecast
                temp_score = 3  # Default
                
                # Calculate base total score (Sea 35 + Wind 20 + Time 25 + Moon 15 + Temp 5 = 100)
                base_score = sea_score + wind_score + time_score + moon_score + temp_score
                
                # =====================================================
                # APPLY UNIFIED OVERRIDE RULES - SAME AS FRONTEND
                # =====================================================
                override_result = apply_score_overrides(
                    base_score, 
                    condizione_mare, 
                    wave_height, 
                    wind_kmh, 
                    time_phase
                )
                
                final_score = override_result['final_score']
                
                # Get aligned label (ensures status matches conditions)
                etichetta = get_aligned_score_label(final_score, condizione_mare, wave_height)
                
                # Format time
                ora = f"{slot_hour:02d}:00"
                
                day_slots.append(ForecastSlot(
                    data=data_str,
                    ora=ora,
                    punteggio=final_score,
                    etichetta=etichetta,
                    vento_kmh=round(wind_kmh, 1),
                    wave_height=round(wave_height, 2),
                    condizione_mare=condizione_mare,
                    temperatura=round(temperatura, 1)
                ))
                
                # Track best for this day
                if final_score > day_best_score:
                    day_best_score = final_score
                    day_best_time = ora
                
                # Track overall best
                if final_score > best_overall_score:
                    best_overall_score = final_score
                    best_overall_day = f"{giorno_nome} {day_date.strftime('%d/%m')}"
                    best_overall_time = ora
            
            # Calculate day average
            punteggio_medio = sum(s.punteggio for s in day_slots) // len(day_slots)
            
            giorni.append(DayForecast(
                data=data_str,
                giorno=f"{giorno_nome} {day_date.strftime('%d/%m')}",
                slots=day_slots,
                punteggio_medio=punteggio_medio,
                migliore_slot=day_best_time
            ))
        
        return ForecastResponse(
            giorni=giorni,
            miglior_giorno=best_overall_day,
            miglior_orario=best_overall_time,
            punteggio_migliore=best_overall_score,
            fase_lunare=fase_lunare
        )
        
    except Exception as e:
        logger.error(f"Forecast error: {e}")
        # Return empty forecast on error
        return ForecastResponse(
            giorni=[],
            miglior_giorno="N/D",
            miglior_orario="N/D",
            punteggio_migliore=0,
            fase_lunare="N/D"
        )


# ============ DATABASE CLEANUP ROUTES ============

@api_router.delete("/admin/cleanup")
async def cleanup_database():
    """
    Admin endpoint to cleanup database:
    - Delete user simuraca@yahoo.it
    - Delete ALL spots
    - Delete catches linked to deleted spots
    """
    results = {
        "user_deleted": False,
        "spots_deleted": 0,
        "catches_deleted": 0
    }
    
    # 1. Delete specific user
    user_result = await db.users.delete_one({"email": "simuraca@yahoo.it"})
    results["user_deleted"] = user_result.deleted_count > 0
    
    # 2. Delete all catches (they reference spots)
    catches_result = await db.catches.delete_many({})
    results["catches_deleted"] = catches_result.deleted_count
    
    # 3. Delete all spots
    spots_result = await db.spots.delete_many({})
    results["spots_deleted"] = spots_result.deleted_count
    
    return {
        "success": True,
        "message": "Database cleanup completato",
        "results": results
    }


@api_router.post("/admin/seed-spots")
async def seed_italian_spots():
    """
    Add 10 excellent Italian eging spots to the database.
    These are real, well-known spots for shore-based squid fishing.
    """
    # 10 top Italian eging spots (public, visible to all)
    italian_spots = [
        {
            "titolo": "Molo di Portofino",
            "descrizione": "Spot iconico in Liguria. Acque profonde vicino alla riva, ideale per eging notturno. Fondale roccioso con alghe.",
            "latitudine": 44.3034,
            "longitudine": 9.2098,
            "pubblico": True,
            "user_id": None,  # System spot
            "created_at": datetime.utcnow()
        },
        {
            "titolo": "Scogliera di Castiglioncello",
            "descrizione": "Costa toscana, rocce a picco sul mare. Ottimo per totani e calamari da settembre a dicembre. Attenzione alle onde.",
            "latitudine": 43.4089,
            "longitudine": 10.4711,
            "pubblico": True,
            "user_id": None,
            "created_at": datetime.utcnow()
        },
        {
            "titolo": "Porto di Siracusa - Ortigia",
            "descrizione": "Sicilia orientale, acque cristalline. Eging eccellente tutto l'anno. Spot protetto dal vento di maestrale.",
            "latitudine": 37.0592,
            "longitudine": 15.2937,
            "pubblico": True,
            "user_id": None,
            "created_at": datetime.utcnow()
        },
        {
            "titolo": "Molo di Polignano a Mare",
            "descrizione": "Puglia, acque profonde e limpide. Ideale al tramonto. Calamari di buona taglia da ottobre a marzo.",
            "latitudine": 40.9942,
            "longitudine": 17.2220,
            "pubblico": True,
            "user_id": None,
            "created_at": datetime.utcnow()
        },
        {
            "titolo": "Scogliere di Capo Caccia",
            "descrizione": "Sardegna nord-ovest, vicino Alghero. Spot spettacolare con fondale roccioso. Attenzione: accessibile solo con mare calmo.",
            "latitudine": 40.5647,
            "longitudine": 8.1597,
            "pubblico": True,
            "user_id": None,
            "created_at": datetime.utcnow()
        },
        {
            "titolo": "Marina di Camerota",
            "descrizione": "Cilento, Campania. Acque pulitissime, ideale per eging estivo. Molte secche vicino riva.",
            "latitudine": 40.0274,
            "longitudine": 15.3737,
            "pubblico": True,
            "user_id": None,
            "created_at": datetime.utcnow()
        },
        {
            "titolo": "Porto di Livorno - Diga Curvilinea",
            "descrizione": "Toscana, spot accessibile e produttivo. Ottimo per principianti. Calamari presenti tutto l'anno.",
            "latitudine": 43.5401,
            "longitudine": 10.2949,
            "pubblico": True,
            "user_id": None,
            "created_at": datetime.utcnow()
        },
        {
            "titolo": "Scogliere di Acitrezza",
            "descrizione": "Sicilia, vicino ai Faraglioni dei Ciclopi. Spot leggendario, fondale vulcanico ricco di cefalopodi.",
            "latitudine": 37.5608,
            "longitudine": 15.1611,
            "pubblico": True,
            "user_id": None,
            "created_at": datetime.utcnow()
        },
        {
            "titolo": "Porto di Ancona - Molo Nord",
            "descrizione": "Marche, Adriatico centrale. Buono per eging invernale. Calamari e seppie di buona taglia.",
            "latitudine": 43.6246,
            "longitudine": 13.5067,
            "pubblico": True,
            "user_id": None,
            "created_at": datetime.utcnow()
        },
        {
            "titolo": "Scogli di Santa Maria di Leuca",
            "descrizione": "Puglia meridionale, punto più a sud. Acque profondissime vicino costa. Spot eccellente per totani giganti.",
            "latitudine": 39.7917,
            "longitudine": 18.3565,
            "pubblico": True,
            "user_id": None,
            "created_at": datetime.utcnow()
        }
    ]
    
    # Insert all spots
    result = await db.spots.insert_many(italian_spots)
    
    return {
        "success": True,
        "message": f"Aggiunti {len(result.inserted_ids)} spot italiani",
        "spot_ids": [str(id) for id in result.inserted_ids]
    }


# ============ GDPR COMPLIANCE ROUTES ============

@api_router.get("/gdpr/privacy-policy")
async def get_privacy_policy():
    """Return the privacy policy content"""
    return {
        "title": "Informativa sulla Privacy - EgiGo",
        "last_updated": "2026-03-17",
        "content": """
# Informativa sulla Privacy

## 1. Titolare del Trattamento
EgiGo App - Applicazione per la pesca sportiva

## 2. Dati Raccolti
Raccogliamo i seguenti dati:
- **Email**: per la registrazione e l'autenticazione
- **Password**: memorizzata in forma criptata (hash)
- **Posizione GPS**: solo quando l'utente la condivide esplicitamente per salvare spot
- **Dati di utilizzo**: spot salvati, catture registrate

## 3. Finalità del Trattamento
I dati sono utilizzati per:
- Fornire il servizio di gestione spot e catture
- Calcolare le condizioni di pesca
- Migliorare l'esperienza utente

## 4. Base Giuridica
Il trattamento è basato sul consenso dell'utente (Art. 6(1)(a) GDPR).

## 5. Conservazione dei Dati
I dati sono conservati fino alla cancellazione dell'account da parte dell'utente.

## 6. Diritti dell'Interessato
Hai diritto a:
- Accedere ai tuoi dati
- Rettificare i dati inesatti
- Cancellare i tuoi dati (diritto all'oblio)
- Esportare i tuoi dati (portabilità)
- Revocare il consenso

## 7. Sicurezza
Utilizziamo crittografia e best practice per proteggere i tuoi dati.

## 8. Contatti
Per esercitare i tuoi diritti, contattaci tramite l'app.
        """
    }

@api_router.get("/gdpr/terms")
async def get_terms_of_service():
    """Return the terms of service"""
    return {
        "title": "Termini di Servizio - EgiGo",
        "last_updated": "2026-03-17",
        "content": """
# Termini di Servizio

## 1. Accettazione
Utilizzando EgiGo, accetti questi termini.

## 2. Descrizione del Servizio
EgiGo è un'app per pescatori che fornisce:
- Condizioni meteo marine in tempo reale
- Consigli per la pesca ai cefalopodi
- Gestione di spot e catture personali

## 3. Account Utente
- Devi avere almeno 16 anni
- Sei responsabile della sicurezza del tuo account
- Un account per persona

## 4. Utilizzo Consentito
L'app è solo per uso personale e non commerciale.

## 5. Limitazione di Responsabilità
Le informazioni meteo sono fornite a scopo indicativo.
Non ci assumiamo responsabilità per decisioni prese basandosi sui dati dell'app.

## 6. Modifiche
Possiamo modificare questi termini con preavviso.
        """
    }

@api_router.delete("/gdpr/delete-account")
async def delete_user_account(current_user: dict = Depends(get_current_user)):
    """
    GDPR: Right to erasure (Right to be forgotten)
    Deletes user account and all associated data
    """
    user_id = current_user["_id"]
    
    results = {
        "user_deleted": False,
        "spots_deleted": 0,
        "catches_deleted": 0
    }
    
    # Delete user's catches
    catches_result = await db.catches.delete_many({"user_id": user_id})
    results["catches_deleted"] = catches_result.deleted_count
    
    # Delete user's spots
    spots_result = await db.spots.delete_many({"user_id": user_id})
    results["spots_deleted"] = spots_result.deleted_count
    
    # Delete user account
    user_result = await db.users.delete_one({"_id": user_id})
    results["user_deleted"] = user_result.deleted_count > 0
    
    return {
        "success": True,
        "message": "Account e tutti i dati associati sono stati eliminati",
        "results": results
    }

@api_router.get("/gdpr/export-data")
async def export_user_data(current_user: dict = Depends(get_current_user)):
    """
    GDPR: Right to data portability
    Returns all user data in a downloadable format
    """
    user_id = current_user["_id"]
    
    # Get user info (excluding password)
    user_data = {
        "email": current_user["email"],
        "is_premium": current_user.get("is_premium", False),
        "created_at": str(current_user.get("created_at", "N/D"))
    }
    
    # Get user's spots
    spots = await db.spots.find({"user_id": user_id}).to_list(1000)
    spots_data = [
        {
            "titolo": s["titolo"],
            "descrizione": s["descrizione"],
            "latitudine": s["latitudine"],
            "longitudine": s["longitudine"],
            "pubblico": s.get("pubblico", False),
            "created_at": str(s.get("created_at", "N/D"))
        }
        for s in spots
    ]
    
    # Get user's catches
    catches = await db.catches.find({"user_id": user_id}).to_list(1000)
    catches_data = [
        {
            "peso": c.get("peso"),
            "tipo_preda": c.get("tipo_preda"),
            "data_ora": str(c.get("data_ora", "N/D")),
            "note": c.get("note", "")
        }
        for c in catches
    ]
    
    return {
        "export_date": str(datetime.utcnow()),
        "user": user_data,
        "spots": spots_data,
        "catches": catches_data
    }

@api_router.post("/gdpr/consent")
async def record_consent(
    privacy_accepted: bool,
    terms_accepted: bool,
    current_user: dict = Depends(get_current_user)
):
    """Record user's GDPR consent"""
    await db.users.update_one(
        {"_id": current_user["_id"]},
        {"$set": {
            "gdpr_privacy_accepted": privacy_accepted,
            "gdpr_terms_accepted": terms_accepted,
            "gdpr_consent_date": datetime.utcnow()
        }}
    )
    return {"success": True, "message": "Consenso registrato"}


# ============ SPOTS ROUTES ============

@api_router.get("/spots", response_model=List[SpotResponse])
async def get_spots(current_user_id: str = None):
    """
    Get spots: public spots + user's own private spots
    If no user is logged in, only public spots are returned
    Legacy spots without 'pubblico' field are treated as private
    """
    # Build query: public spots OR user's own spots
    if current_user_id:
        try:
            user_oid = ObjectId(current_user_id)
            query = {"$or": [{"pubblico": True}, {"user_id": user_oid}]}
        except:
            query = {"pubblico": True}
    else:
        query = {"pubblico": True}
    
    spots = await db.spots.find(query).to_list(1000)
    
    return [
        SpotResponse(
            id=str(spot["_id"]),
            user_id=str(spot["user_id"]),
            titolo=spot["titolo"],
            descrizione=spot["descrizione"],
            latitudine=spot["latitudine"],
            longitudine=spot["longitudine"],
            pubblico=spot.get("pubblico", False),
            is_owner=bool(current_user_id and str(spot["user_id"]) == current_user_id),
            created_at=spot["created_at"]
        )
        for spot in spots
    ]

@api_router.get("/spots/my", response_model=List[SpotResponse])
async def get_my_spots(current_user: dict = Depends(get_current_user)):
    """Get only user's own spots (both public and private)"""
    spots = await db.spots.find({"user_id": current_user["_id"]}).to_list(1000)
    user_id_str = str(current_user["_id"])
    
    return [
        SpotResponse(
            id=str(spot["_id"]),
            user_id=str(spot["user_id"]),
            titolo=spot["titolo"],
            descrizione=spot["descrizione"],
            latitudine=spot["latitudine"],
            longitudine=spot["longitudine"],
            pubblico=spot.get("pubblico", False),
            is_owner=True,
            created_at=spot["created_at"]
        )
        for spot in spots
    ]

@api_router.post("/spots", response_model=SpotResponse)
async def create_spot(
    spot_data: SpotCreate,
    current_user: dict = Depends(get_current_user)
):
    new_spot = {
        "user_id": current_user["_id"],
        "titolo": spot_data.titolo,
        "descrizione": spot_data.descrizione,
        "latitudine": spot_data.latitudine,
        "longitudine": spot_data.longitudine,
        "pubblico": spot_data.pubblico,
        "created_at": datetime.utcnow()
    }
    
    result = await db.spots.insert_one(new_spot)
    new_spot["_id"] = result.inserted_id
    
    return SpotResponse(
        id=str(new_spot["_id"]),
        user_id=str(new_spot["user_id"]),
        titolo=new_spot["titolo"],
        descrizione=new_spot["descrizione"],
        latitudine=new_spot["latitudine"],
        longitudine=new_spot["longitudine"],
        pubblico=new_spot["pubblico"],
        is_owner=True,
        created_at=new_spot["created_at"]
    )

@api_router.get("/spots/{spot_id}", response_model=SpotResponse)
async def get_spot(spot_id: str, current_user_id: str = None):
    try:
        spot = await db.spots.find_one({"_id": ObjectId(spot_id)})
    except:
        raise HTTPException(status_code=400, detail="ID spot non valido")
    
    if not spot:
        raise HTTPException(status_code=404, detail="Spot non trovato")
    
    # Check if user can view this spot (public or owner)
    is_public = spot.get("pubblico", False)
    is_owner = current_user_id and str(spot["user_id"]) == current_user_id
    
    if not is_public and not is_owner:
        raise HTTPException(status_code=403, detail="Spot privato")
    
    return SpotResponse(
        id=str(spot["_id"]),
        user_id=str(spot["user_id"]),
        titolo=spot["titolo"],
        descrizione=spot["descrizione"],
        latitudine=spot["latitudine"],
        longitudine=spot["longitudine"],
        pubblico=is_public,
        is_owner=is_owner,
        created_at=spot["created_at"]
    )

@api_router.put("/spots/{spot_id}", response_model=SpotResponse)
async def update_spot(
    spot_id: str,
    spot_update: SpotUpdate,
    current_user: dict = Depends(get_current_user)
):
    """Update a spot - only owner can update"""
    try:
        spot = await db.spots.find_one({"_id": ObjectId(spot_id)})
    except:
        raise HTTPException(status_code=400, detail="ID spot non valido")
    
    if not spot:
        raise HTTPException(status_code=404, detail="Spot non trovato")
    
    # Check ownership
    if spot["user_id"] != current_user["_id"]:
        raise HTTPException(status_code=403, detail="Non autorizzato a modificare questo spot")
    
    # Build update dict
    update_data = {}
    if spot_update.titolo is not None:
        update_data["titolo"] = spot_update.titolo.strip()
    if spot_update.descrizione is not None:
        update_data["descrizione"] = spot_update.descrizione.strip()
    if spot_update.latitudine is not None:
        update_data["latitudine"] = spot_update.latitudine
    if spot_update.longitudine is not None:
        update_data["longitudine"] = spot_update.longitudine
    if spot_update.pubblico is not None:
        update_data["pubblico"] = spot_update.pubblico
    
    if update_data:
        await db.spots.update_one(
            {"_id": ObjectId(spot_id)},
            {"$set": update_data}
        )
    
    # Get updated spot
    updated_spot = await db.spots.find_one({"_id": ObjectId(spot_id)})
    
    return SpotResponse(
        id=str(updated_spot["_id"]),
        user_id=str(updated_spot["user_id"]),
        titolo=updated_spot["titolo"],
        descrizione=updated_spot["descrizione"],
        latitudine=updated_spot["latitudine"],
        longitudine=updated_spot["longitudine"],
        pubblico=updated_spot.get("pubblico", False),
        is_owner=True,
        created_at=updated_spot["created_at"]
    )

@api_router.delete("/spots/{spot_id}")
async def delete_spot(
    spot_id: str,
    current_user: dict = Depends(get_current_user)
):
    """Delete a spot - only owner can delete"""
    try:
        spot = await db.spots.find_one({"_id": ObjectId(spot_id)})
    except:
        raise HTTPException(status_code=400, detail="ID spot non valido")
    
    if not spot:
        raise HTTPException(status_code=404, detail="Spot non trovato")
    
    # Check ownership
    if spot["user_id"] != current_user["_id"]:
        raise HTTPException(status_code=403, detail="Non autorizzato a eliminare questo spot")
    
    # Delete the spot
    await db.spots.delete_one({"_id": ObjectId(spot_id)})
    
    return {"success": True, "message": "Spot eliminato con successo"}


# ============ CATCHES ROUTES ============

@api_router.get("/catches", response_model=List[CatchResponse])
async def get_catches(current_user: dict = Depends(get_current_user)):
    catches = await db.catches.find({"user_id": current_user["_id"]}).sort("data_ora", -1).to_list(1000)
    
    result = []
    for catch in catches:
        # Get spot title
        spot = await db.spots.find_one({"_id": ObjectId(catch["spot_id"])})
        spot_titolo = spot["titolo"] if spot else "Spot sconosciuto"
        
        result.append(
            CatchResponse(
                id=str(catch["_id"]),
                user_id=str(catch["user_id"]),
                spot_id=str(catch["spot_id"]),
                peso=catch["peso"],
                foto_base64=catch.get("foto_base64"),
                data_ora=catch["data_ora"],
                tipo_preda=catch.get("tipo_preda", "calamaro"),
                nome=catch.get("nome"),
                ora_cattura=catch.get("ora_cattura"),
                numero_pezzi=catch.get("numero_pezzi"),
                created_at=catch["created_at"],
                spot_titolo=spot_titolo,
                wave_height=catch.get("wave_height"),
                wind_kmh=catch.get("wind_kmh"),
                temperature=catch.get("temperature"),
                moon_phase=catch.get("moon_phase"),
                moon_illumination=catch.get("moon_illumination"),
                sea_condition=catch.get("sea_condition"),
                time_of_day=catch.get("time_of_day"),
                fishing_score=catch.get("fishing_score")
            )
        )
    
    return result

@api_router.post("/catches", response_model=CatchResponse)
async def create_catch(
    catch_data: CatchCreate,
    current_user: dict = Depends(get_current_user)
):
    # Verify spot exists
    try:
        spot = await db.spots.find_one({"_id": ObjectId(catch_data.spot_id)})
    except:
        raise HTTPException(status_code=400, detail="ID spot non valido")
    
    if not spot:
        raise HTTPException(status_code=404, detail="Spot non trovato")
    
    new_catch = {
        "user_id": current_user["_id"],
        "spot_id": ObjectId(catch_data.spot_id),
        "peso": catch_data.peso,
        "foto_base64": catch_data.foto_base64,
        "data_ora": catch_data.data_ora,
        "tipo_preda": catch_data.tipo_preda,
        "nome": catch_data.nome,
        # Environmental conditions at catch time
        "wave_height": catch_data.wave_height,
        "wind_kmh": catch_data.wind_kmh,
        "temperature": catch_data.temperature,
        "moon_phase": catch_data.moon_phase,
        "moon_illumination": catch_data.moon_illumination,
        "sea_condition": catch_data.sea_condition,
        "time_of_day": catch_data.time_of_day,
        "fishing_score": catch_data.fishing_score,
        "created_at": datetime.utcnow()
    }
    
    result = await db.catches.insert_one(new_catch)
    new_catch["_id"] = result.inserted_id
    
    return CatchResponse(
        id=str(new_catch["_id"]),
        user_id=str(new_catch["user_id"]),
        spot_id=str(new_catch["spot_id"]),
        peso=new_catch["peso"],
        foto_base64=new_catch["foto_base64"],
        data_ora=new_catch["data_ora"],
        tipo_preda=new_catch["tipo_preda"],
        nome=new_catch.get("nome"),
        ora_cattura=new_catch.get("ora_cattura"),
        numero_pezzi=new_catch.get("numero_pezzi"),
        created_at=new_catch["created_at"],
        spot_titolo=spot["titolo"],
        wave_height=new_catch.get("wave_height"),
        wind_kmh=new_catch.get("wind_kmh"),
        temperature=new_catch.get("temperature"),
        moon_phase=new_catch.get("moon_phase"),
        moon_illumination=new_catch.get("moon_illumination"),
        sea_condition=new_catch.get("sea_condition"),
        time_of_day=new_catch.get("time_of_day"),
        fishing_score=new_catch.get("fishing_score")
    )

@api_router.get("/catches/{catch_id}", response_model=CatchResponse)
async def get_catch(
    catch_id: str,
    current_user: dict = Depends(get_current_user)
):
    try:
        catch = await db.catches.find_one({
            "_id": ObjectId(catch_id),
            "user_id": current_user["_id"]
        })
    except:
        raise HTTPException(status_code=400, detail="ID cattura non valido")
    
    if not catch:
        raise HTTPException(status_code=404, detail="Cattura non trovata")
    
    # Get spot title
    spot = await db.spots.find_one({"_id": catch["spot_id"]})
    spot_titolo = spot["titolo"] if spot else "Spot sconosciuto"
    
    return CatchResponse(
        id=str(catch["_id"]),
        user_id=str(catch["user_id"]),
        spot_id=str(catch["spot_id"]),
        peso=catch["peso"],
        foto_base64=catch.get("foto_base64"),
        data_ora=catch["data_ora"],
        tipo_preda=catch.get("tipo_preda", "calamaro"),
        nome=catch.get("nome"),
        ora_cattura=catch.get("ora_cattura"),
        numero_pezzi=catch.get("numero_pezzi"),
        created_at=catch["created_at"],
        spot_titolo=spot_titolo,
        wave_height=catch.get("wave_height"),
        wind_kmh=catch.get("wind_kmh"),
        temperature=catch.get("temperature"),
        moon_phase=catch.get("moon_phase"),
        moon_illumination=catch.get("moon_illumination"),
        sea_condition=catch.get("sea_condition"),
        time_of_day=catch.get("time_of_day"),
        fishing_score=catch.get("fishing_score")
    )

# Update catch
@api_router.put("/catches/{catch_id}", response_model=CatchResponse)
async def update_catch(
    catch_id: str,
    catch_update: CatchUpdate,
    current_user: dict = Depends(get_current_user)
):
    try:
        catch = await db.catches.find_one({
            "_id": ObjectId(catch_id),
            "user_id": current_user["_id"]
        })
    except:
        raise HTTPException(status_code=400, detail="ID cattura non valido")
    
    if not catch:
        raise HTTPException(status_code=404, detail="Cattura non trovata")
    
    # Build update dict with all editable fields
    update_data = {}
    if catch_update.nome is not None:
        update_data["nome"] = catch_update.nome if catch_update.nome.strip() else None
    if catch_update.peso is not None:
        update_data["peso"] = catch_update.peso
    if catch_update.tipo_preda is not None:
        update_data["tipo_preda"] = catch_update.tipo_preda
    if catch_update.spot_id is not None:
        # Verify spot exists
        try:
            spot_check = await db.spots.find_one({"_id": ObjectId(catch_update.spot_id)})
            if spot_check:
                update_data["spot_id"] = ObjectId(catch_update.spot_id)
        except:
            pass
    if catch_update.data_ora is not None:
        update_data["data_ora"] = catch_update.data_ora
    if catch_update.ora_cattura is not None:
        update_data["ora_cattura"] = catch_update.ora_cattura
    if catch_update.numero_pezzi is not None:
        update_data["numero_pezzi"] = catch_update.numero_pezzi
    if catch_update.foto_base64 is not None:
        # Empty string means remove photo, otherwise set new photo
        update_data["foto_base64"] = catch_update.foto_base64 if catch_update.foto_base64 else None
    
    if update_data:
        await db.catches.update_one(
            {"_id": ObjectId(catch_id)},
            {"$set": update_data}
        )
    
    # Get updated catch
    updated_catch = await db.catches.find_one({"_id": ObjectId(catch_id)})
    spot = await db.spots.find_one({"_id": updated_catch["spot_id"]})
    spot_titolo = spot["titolo"] if spot else "Spot sconosciuto"
    
    return CatchResponse(
        id=str(updated_catch["_id"]),
        user_id=str(updated_catch["user_id"]),
        spot_id=str(updated_catch["spot_id"]),
        peso=updated_catch["peso"],
        foto_base64=updated_catch.get("foto_base64"),
        data_ora=updated_catch["data_ora"],
        tipo_preda=updated_catch.get("tipo_preda", "calamaro"),
        nome=updated_catch.get("nome"),
        ora_cattura=updated_catch.get("ora_cattura"),
        numero_pezzi=updated_catch.get("numero_pezzi"),
        created_at=updated_catch["created_at"],
        spot_titolo=spot_titolo,
        wave_height=updated_catch.get("wave_height"),
        wind_kmh=updated_catch.get("wind_kmh"),
        temperature=updated_catch.get("temperature"),
        moon_phase=updated_catch.get("moon_phase"),
        moon_illumination=updated_catch.get("moon_illumination"),
        sea_condition=updated_catch.get("sea_condition"),
        time_of_day=updated_catch.get("time_of_day"),
        fishing_score=updated_catch.get("fishing_score")
    )

# Delete catch
@api_router.delete("/catches/{catch_id}")
async def delete_catch(
    catch_id: str,
    current_user: dict = Depends(get_current_user)
):
    try:
        catch = await db.catches.find_one({
            "_id": ObjectId(catch_id),
            "user_id": current_user["_id"]
        })
    except:
        raise HTTPException(status_code=400, detail="ID cattura non valido")
    
    if not catch:
        raise HTTPException(status_code=404, detail="Cattura non trovata")
    
    await db.catches.delete_one({"_id": ObjectId(catch_id)})
    
    return {"success": True, "message": "Cattura eliminata con successo"}


# ============ CONDITIONS ROUTE ============

@api_router.get("/conditions", response_model=ConditionsResponse)
async def get_conditions():
    conditions = calculate_fishing_score()
    return ConditionsResponse(**conditions)


# ============ WEATHER ROUTE ============

def get_sea_condition_from_wave(wave_height: float, wind_speed: float = None) -> str:
    """
    Determine sea condition from actual wave height data.
    Falls back to wind-based estimation if no wave data available.
    UPDATED THRESHOLDS for realistic eging fishing
    """
    if wave_height is not None:
        # Use real wave data with UPDATED THRESHOLDS
        if wave_height <= 0.2:
            return "Piatto"
        elif wave_height <= 0.5:
            return "Calmo"
        elif wave_height <= 0.8:
            return "Poco Mosso"
        elif wave_height <= 1.2:
            return "Mosso"
        else:
            return "Molto Mosso"
    elif wind_speed is not None:
        # Fallback to wind-based estimation
        if wind_speed <= 5:
            return "Piatto"
        elif wind_speed <= 12:
            return "Calmo"
        elif wind_speed <= 20:
            return "Poco Mosso"
        elif wind_speed <= 30:
            return "Mosso"
        else:
            return "Molto Mosso"
    else:
        return "N/D"

def get_time_of_day(current_time: datetime, sunrise: str, sunset: str) -> str:
    """
    Determine time of day based on actual sunrise/sunset times
    Returns: Notte, Alba, Giorno, Tramonto
    """
    try:
        # Parse sunrise/sunset times (format: "2026-03-17T06:27")
        sunrise_time = datetime.fromisoformat(sunrise)
        sunset_time = datetime.fromisoformat(sunset)
        
        # Define time windows (30 minutes before/after for transitions)
        alba_start = sunrise_time - timedelta(minutes=30)
        alba_end = sunrise_time + timedelta(minutes=30)
        tramonto_start = sunset_time - timedelta(minutes=30)
        tramonto_end = sunset_time + timedelta(minutes=30)
        
        if current_time < alba_start:
            return "Notte"
        elif alba_start <= current_time <= alba_end:
            return "Alba"
        elif alba_end < current_time < tramonto_start:
            return "Giorno"
        elif tramonto_start <= current_time <= tramonto_end:
            return "Tramonto"
        else:
            return "Notte"
    except Exception as e:
        logger.error(f"Error calculating time of day: {e}")
        # Fallback to simple hour-based logic
        hour = current_time.hour
        if 5 <= hour <= 7:
            return "Alba"
        elif 8 <= hour <= 17:
            return "Giorno"
        elif 18 <= hour <= 20:
            return "Tramonto"
        return "Notte"

@api_router.get("/weather", response_model=WeatherResponse)
async def get_weather(lat: float, lon: float):
    """
    Fetch real weather data from Open-Meteo API including:
    - Current weather (temperature, wind, gusts)
    - Marine data (wave height, sea surface temperature)
    - Sunrise/sunset for accurate time of day
    """
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            # Fetch weather data with sunrise/sunset AND wind gusts
            weather_response = await client.get(
                "https://api.open-meteo.com/v1/forecast",
                params={
                    "latitude": lat,
                    "longitude": lon,
                    "current": "temperature_2m,wind_speed_10m,wind_direction_10m,wind_gusts_10m",
                    "daily": "sunrise,sunset",
                    "timezone": "auto",
                    "forecast_days": 1
                }
            )
            weather_response.raise_for_status()
            weather_data = weather_response.json()
            
            # Fetch marine data for wave height AND sea surface temperature
            wave_height = None
            water_temperature = None
            try:
                marine_response = await client.get(
                    "https://marine-api.open-meteo.com/v1/marine",
                    params={
                        "latitude": lat,
                        "longitude": lon,
                        "current": "wave_height,sea_surface_temperature",
                        "timezone": "auto"
                    }
                )
                if marine_response.status_code == 200:
                    marine_data = marine_response.json()
                    current_marine = marine_data.get("current", {})
                    wave_height = current_marine.get("wave_height")
                    water_temperature = current_marine.get("sea_surface_temperature")
            except Exception as marine_error:
                logger.warning(f"Marine API failed, using fallback: {marine_error}")
            
            current = weather_data.get("current", {})
            daily = weather_data.get("daily", {})
            
            # Get sunrise/sunset
            sunrise = daily.get("sunrise", [None])[0]
            sunset = daily.get("sunset", [None])[0]
            
            # Calculate time of day
            now = datetime.now()
            time_of_day = get_time_of_day(now, sunrise, sunset) if sunrise and sunset else None
            
            # Get wind data
            wind_speed = current.get("wind_speed_10m", 0)
            wind_gusts = current.get("wind_gusts_10m")
            
            # Calculate sea condition from wave height (with wind fallback)
            sea_condition = get_sea_condition_from_wave(wave_height, wind_speed)
            
            return WeatherResponse(
                temperature=current.get("temperature_2m", 0),
                wind_speed=wind_speed,
                wind_direction=current.get("wind_direction_10m", 0),
                latitude=lat,
                longitude=lon,
                wave_height=wave_height,
                sea_condition=sea_condition,
                sunrise=sunrise,
                sunset=sunset,
                time_of_day=time_of_day,
                water_temperature=water_temperature,
                wind_gusts=wind_gusts
            )
    except httpx.TimeoutException:
        raise HTTPException(status_code=504, detail="Timeout nel recupero dati meteo")
    except httpx.HTTPError as e:
        logger.error(f"Weather API error: {e}")
        raise HTTPException(status_code=502, detail="Errore nel servizio meteo")
    except Exception as e:
        logger.error(f"Unexpected weather error: {e}")
        raise HTTPException(status_code=500, detail="Errore interno")


# ============ ADMIN ROUTES (MVP - No Auth) ============

@api_router.get("/admin/users")
async def get_all_users():
    """Get all users for admin panel (MVP - no auth required)"""
    users = await db.users.find().to_list(1000)
    return [
        {
            "id": str(user["_id"]),
            "email": user["email"],
            "created_at": user.get("created_at").isoformat() if user.get("created_at") else "N/A"
        }
        for user in users
    ]

@api_router.get("/admin/spots")
async def get_all_spots_admin():
    """Get all spots with user info for admin panel"""
    spots = await db.spots.find().to_list(1000)
    result = []
    for spot in spots:
        user = await db.users.find_one({"_id": spot["user_id"]})
        result.append({
            "id": str(spot["_id"]),
            "titolo": spot["titolo"],
            "descrizione": spot["descrizione"],
            "latitudine": spot["latitudine"],
            "longitudine": spot["longitudine"],
            "user_id": str(spot["user_id"]),
            "user_email": user["email"] if user else "Unknown",
            "created_at": spot.get("created_at").isoformat() if spot.get("created_at") else "N/A"
        })
    return result

@api_router.get("/admin/catches")
async def get_all_catches_admin():
    """Get all catches with details for admin panel"""
    catches = await db.catches.find().to_list(1000)
    result = []
    for catch in catches:
        user = await db.users.find_one({"_id": catch["user_id"]})
        spot = await db.spots.find_one({"_id": catch["spot_id"]})
        result.append({
            "id": str(catch["_id"]),
            "peso": catch["peso"],
            "data_ora": catch["data_ora"].isoformat() if catch.get("data_ora") else "N/A",
            "spot_id": str(catch["spot_id"]),
            "spot_titolo": spot["titolo"] if spot else "Unknown",
            "user_id": str(catch["user_id"]),
            "user_email": user["email"] if user else "Unknown",
            "created_at": catch.get("created_at").isoformat() if catch.get("created_at") else "N/A"
        })
    return result


# ============ AI ASSISTANT ROUTES ============

class AssistantRequest(BaseModel):
    message: str
    session_id: str
    context: dict = {}  # Contains weather, moon, sea conditions etc.

class AssistantResponse(BaseModel):
    response: str
    intent: str  # "question", "command_catch", "command_spot", "general"
    extracted_data: Optional[dict] = None  # For commands: extracted weight, type, etc.

# System prompt for the AI assistant - EXPERT EGING PROFESSIONAL
AI_SYSTEM_PROMPT = """Sei un ESPERTO PROFESSIONISTA di EGING, ispirato al metodo Kawakami giapponese.
NON sei un chatbot generico. Sei come avere un pescatore professionista accanto.

## LA TUA EXPERTISE

MARCHE EGI che conosci a fondo:
- YAMASHITA: EGI-OH K (top di gamma), EGI-OH Q Live, EGI-OH LIVE Search
- DUEL: EZ-Q Cast, EZ-Q Dart Master, EZ-Q Magcast
- YO-ZURI: Squid Jig Ultra, Aurie-Q Ace, Crystal 3D
- DAIWA: Emeraldas serie Peak/Dart/Rattle
- SHIMANO: Sephia Clinch, Sephia Flash Boost

MISURE EGI:
- 2.5 (8cm): acque basse, cefalopodi piccoli, calamari cauti
- 3.0 (10cm): misura universale, ideale quasi sempre
- 3.5 (11cm): acque profonde, corrente forte, cefalopodi attivi

AFFONDAMENTO (sinking rate):
- SHALLOW (8-10 sec/m): acque basse <5m, fondali erbosi, cefalopodi sospesi
- BASIC/NORMAL (3-4 sec/m): uso standard, la maggior parte delle situazioni
- DEEP (1.5-2 sec/m): profondità >15m, correnti forti, vento forte

COLORI secondo Kawakami:
- NATURALI (sarda, sugarello, gamberetto): acqua limpida, luce forte
- ORO/ARGENTO: sole pieno, massima rifrazione
- ROSA/ARANCIO: nuvoloso, crepuscolo, sempre versatili
- GLOW VERDE: notte luna nuova, acqua torbida
- 490 GLOW (azzurro): notte, luce UV residua
- KEIMURA (UV): mezzogiorno, UV alta, acqua limpida
- ROSSO/NERO: luna piena, creare silhouette

ATTREZZATURA:
- TRECCIATO PE: 0.4-0.6 (consiglia PE 0.5 come standard)
- LEADER FLUOROCARBON: 1.5-2.0 (10-14 lb), 1.5-2 metri
- CANNA: 7-8.6 piedi, azione M o MH
- MULINELLO: 2500-3000, recupero medio-alto

NODI:
- FG KNOT: il migliore per PE+fluoro, sottile e resistente
- PR KNOT: alternativa all'FG, più facile da imparare
- IMPROVED CLINCH: fluoro-egi, semplice ed efficace
- UNI KNOT: universale, buono per iniziare

TECNICHE JERK:
- SOFT JERK: 2-3 colpi corti, cefalopodi apatici, acqua calma
- AGGRESSIVE JERK: colpi decisi, mare mosso, attivare l'attacco
- LIFT & FALL: solleva e lascia cadere, fondali, seppie
- DART: scatti laterali rapidi, calamari attivi
- STOP & GO: recupero + pause lunghe, seppia

## CONTESTO ATTUALE
{context}

## STORICO CATTURE UTENTE
{history}

## COME RISPONDI

1. SEMPRE in italiano
2. BREVE e PRATICO (2-3 frasi max per domande semplici)
3. Come un pescatore esperto, NON come un'enciclopedia
4. Collegati SEMPRE alle condizioni attuali se rilevanti

ESEMPI DI RISPOSTE:

Domanda: "che egi uso?"
Risposta: "Con questo mare poco mosso e luna nuova, vai su un Yamashita 3.0 deep, colore glow verde. Jerk morbidi con pause lunghe."

Domanda: "che trecciato?"
Risposta: "PE 0.5 è perfetto per l'eging. 150m bastano. Consiglio Daiwa J-Braid o YGK."

Domanda: "che finale fluorocarbon?"
Risposta: "1.75 (12lb) da 1.5-2 metri. Seaguar o Sunline sono top. Cambialo se si rovina."

Domanda: "che nodo fare?"
Risposta: "FG knot per PE-fluoro, è il migliore. Se sei alle prime armi, PR knot è più facile. Per fluoro-egi vai di improved clinch."

Domanda: "come jerkare?"
Risposta: "Con mare calmo: jerk corti e morbidi (2-3 colpi), poi pausa 5-8 secondi. Lascia che l'egi affondi bene. Le tocche arrivano spesso in caduta."

Domanda: "meglio calamari o seppie oggi?"
Risposta: "Con queste condizioni (notte, luna nuova) punterei sui calamari. Seppie meglio al tramonto su fondali sabbiosi."

Domanda: "conviene uscire?"
Risposta: "Sì/No + motivazione pratica in 1 frase."

## RICONOSCIMENTO COMANDI

Se l'utente dice:
- "aggiungi cattura" / "ho preso" / "catturato" -> Estrai peso e tipo
- "salva spot" / "segna posizione" -> Vuole salvare uno spot

FORMATO per comandi (dopo la risposta):
[INTENT:command_catch] o [INTENT:command_spot]
[DATA:peso=500,tipo=calamaro]

Esempio:
"Ho preso un calamaro da 400g"
"Bel calamaro! Con luna nuova i risultati sono sempre buoni. Lo registro nel diario.
[INTENT:command_catch]
[DATA:peso=400,tipo=calamaro]"

## REGOLA D'ORO
Rispondi come se fossi sul molo accanto all'utente, non come un manuale. Pratico, diretto, utile.

## TONO E STILE - IMPORTANTE
- NON dire MAI "buona pesca", "buona fortuna", "in bocca al lupo" o frasi simili
- NON usare chiusure generiche o cliché
- Concludi con informazioni utili, NON con auguri
- Mantieni un tono professionale ed esperto
- Sii informativo fino all'ultima parola
"""

@api_router.post("/assistant/chat", response_model=AssistantResponse)
async def chat_with_assistant(request: AssistantRequest):
    """
    AI Assistant endpoint for eging advice and commands
    """
    if not EMERGENT_LLM_KEY:
        raise HTTPException(status_code=500, detail="AI service not configured")
    
    try:
        # Build context string
        context_str = ""
        if request.context:
            ctx = request.context
            context_str = f"""
- Vento: {ctx.get('vento_kmh', 'N/D')} km/h {ctx.get('direzione_vento', '')}
- Mare: {ctx.get('condizione_mare', 'N/D')} (onde: {ctx.get('wave_height', 'N/D')}m)
- Temperatura: {ctx.get('temperatura', 'N/D')}°C
- Momento: {ctx.get('momento', 'N/D')}
- Fase lunare: {ctx.get('fase_lunare', 'N/D')} ({ctx.get('illuminazione_luna', 'N/D')}% illuminata)
- Punteggio pesca: {ctx.get('fishing_score', 'N/D')}/100
"""
        
        # Build history string from user's past catches
        history_str = "Nessuna cattura registrata"
        if request.context and request.context.get('user_id'):
            try:
                user_catches = await db.catches.find({
                    "user_id": ObjectId(request.context.get('user_id'))
                }).sort("data_ora", -1).limit(10).to_list(10)
                
                if user_catches:
                    history_items = []
                    for c in user_catches:
                        # Convert weight to grams if stored in kg (less than 10 means kg)
                        peso = c.get('peso', 0)
                        peso_str = f"{int(peso)}g" if peso > 10 else f"{int(peso * 1000)}g"
                        
                        catch_info = f"- {c.get('tipo_preda', 'calamaro').capitalize()} {peso_str}"
                        
                        # Add conditions if available
                        conditions = []
                        if c.get('sea_condition'):
                            conditions.append(f"mare {c.get('sea_condition').lower()}")
                        if c.get('time_of_day'):
                            conditions.append(c.get('time_of_day').lower())
                        if c.get('moon_phase'):
                            conditions.append(c.get('moon_phase').split()[0].lower())
                        if c.get('fishing_score'):
                            conditions.append(f"score {c.get('fishing_score')}")
                        
                        if conditions:
                            catch_info += f" ({', '.join(conditions)})"
                        
                        # Add date if available
                        if c.get('data_ora'):
                            try:
                                data_str = c.get('data_ora').strftime('%d/%m')
                                catch_info += f" - {data_str}"
                            except:
                                pass
                        
                        history_items.append(catch_info)
                    history_str = "\n".join(history_items)
            except Exception as e:
                logger.warning(f"Error loading catch history: {e}")
                history_str = "Nessuna cattura registrata"
        
        system_message = AI_SYSTEM_PROMPT.format(
            context=context_str if context_str else "Non disponibile",
            history=history_str
        )
        
        # Create chat instance
        chat = LlmChat(
            api_key=EMERGENT_LLM_KEY,
            session_id=request.session_id,
            system_message=system_message
        ).with_model("openai", "gpt-4o")
        
        # Send message
        user_message = UserMessage(text=request.message)
        response_text = await chat.send_message(user_message)
        
        # Parse intent and data from response
        intent = "question"
        extracted_data = None
        clean_response = response_text
        
        # Check for intent markers
        if "[INTENT:command_catch]" in response_text:
            intent = "command_catch"
            clean_response = response_text.split("[INTENT:")[0].strip()
        elif "[INTENT:command_spot]" in response_text:
            intent = "command_spot"
            clean_response = response_text.split("[INTENT:")[0].strip()
        
        # Extract data if present
        if "[DATA:" in response_text:
            try:
                data_start = response_text.find("[DATA:") + 6
                data_end = response_text.find("]", data_start)
                data_str = response_text[data_start:data_end]
                
                extracted_data = {}
                for pair in data_str.split(","):
                    if "=" in pair:
                        key, value = pair.split("=", 1)
                        # Convert peso to float if numeric
                        if key == "peso":
                            try:
                                extracted_data[key] = float(value)
                            except:
                                extracted_data[key] = value
                        else:
                            extracted_data[key] = value
            except Exception as e:
                logger.error(f"Error parsing data: {e}")
        
        return AssistantResponse(
            response=clean_response,
            intent=intent,
            extracted_data=extracted_data
        )
        
    except Exception as e:
        logger.error(f"AI Assistant error: {e}")
        raise HTTPException(status_code=500, detail=f"Errore assistente: {str(e)}")


# Include the router in the main app
app.include_router(api_router)

app.add_middleware(
    CORSMiddleware,
    allow_credentials=True,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


