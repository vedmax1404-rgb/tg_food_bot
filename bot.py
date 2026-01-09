import asyncio
import io
import requests
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from aiogram import Bot, Dispatcher
from aiogram.types import Message, BufferedInputFile
from aiogram.filters import Command, CommandStart
from aiogram.fsm.state import StatesGroup, State
from aiogram.fsm.context import FSMContext
from config import TOKEN, WEATHER_KEY

bot = Bot(token=TOKEN)
dp = Dispatcher()

storage = {}

class profile_flow(StatesGroup):
    weight = State()
    height = State()
    age = State()
    activity = State()
    city = State()

class food_flow(StatesGroup):
    grams = State()

def fetch_weather(city_name: str):
    response = requests.get(
        "https://api.openweathermap.org/data/2.5/weather",
        params={
            "q": city_name,
            "appid": WEATHER_KEY,
            "units": "metric"
        }
    )
    return response.json()

def fetch_food(product_name: str):
    response = requests.get(
        "https://world.openfoodfacts.org/cgi/search.pl",
        params={
            "action": "process",
            "search_terms": product_name,
            "json": True
        }
    )

    if response.status_code != 200:
        return None
    items = response.json().get("products", [])
    if not items:
        return None
    item = items[0]
    kcal = item.get("nutriments", {}).get("energy-kcal_100g", 0)
    return {
        "title": item.get("product_name", product_name),
        "kcal": kcal
    }

@dp.message(CommandStart())
async def hello(msg: Message):
    await msg.answer(
        "/set_profile\n"
        "/log_water <мл>\n"
        "/log_food <продукт>\n"
        "/log_workout <тип> <мин>\n"
        "/check_progress\n"
        "/show_graphs"
    )

@dp.message(Command("set_profile"))
async def start_profile(msg: Message, state: FSMContext):
    await msg.answer("Веш вес (кг)?")
    await state.set_state(profile_flow.weight)

@dp.message(profile_flow.weight)
async def profile_weight(msg: Message, state: FSMContext):
    await state.update_data(weight=int(msg.text))
    await msg.answer("Ваш рост (см)?")
    await state.set_state(profile_flow.height)

@dp.message(profile_flow.height)
async def profile_height(msg: Message, state: FSMContext):
    await state.update_data(height=int(msg.text))
    await msg.answer("Ваш возраст?")
    await state.set_state(profile_flow.age)

@dp.message(profile_flow.age)
async def profile_age(msg: Message, state: FSMContext):
    await state.update_data(age=int(msg.text))
    await msg.answer("Ваша дневная активность (мин)?")
    await state.set_state(profile_flow.activity)

@dp.message(profile_flow.activity)
async def profile_activity(msg: Message, state: FSMContext):
    await state.update_data(activity=int(msg.text))
    await msg.answer("Ваш город?")
    await state.set_state(profile_flow.city)

@dp.message(profile_flow.city)
async def profile_finish(msg: Message, state: FSMContext):
    data = await state.get_data()
    uid = msg.from_user.id
    weight = data["weight"]
    height = data["height"]
    age = data["age"]
    activity = data["activity"]
    city = msg.text
    water_target = weight * 30 + (activity // 30) * 500
    calorie_target = 10 * weight + 6.25 * height - 5 * age
    if activity >= 30:
        calorie_target += 200
    weather = fetch_weather(city)
    if weather.get("main") and weather["main"]["temp"] > 25:
        water_target += 500
    storage[uid] = {
        "water_goal": water_target,
        "cal_goal": calorie_target,
        "water_now": 0,
        "cal_now": 0,
        "burned": 0,
        "water_history": [],
        "cal_history": []
    }

    await state.clear()

    await msg.answer(
        f"Профиль сохранен.\n"
        f"Вода: {water_target} мл\n"
        f"Калории: {int(calorie_target)} ккал"
    )


@dp.message(Command("log_water"))
async def add_water(msg: Message):
    uid = msg.from_user.id
    if uid not in storage:
        await msg.answer("Требуется настроить профиль: /set_profile")
        return

    try:
        amount = int(msg.text.split()[1])
    except:
        await msg.answer("Требуется формат: /log_water <мл>")
        return

    user = storage[uid]
    user["water_now"] += amount
    user["water_history"].append(user["water_now"])
    left = max(user["water_goal"] - user["water_now"], 0)
    await msg.answer(f"+{amount} мл\nОсталось: {left} мл")


@dp.message(Command("log_food"))
async def start_food(msg: Message, state: FSMContext):
    uid = msg.from_user.id
    if uid not in storage:
        await msg.answer("Требуется настроить профиль: /set_profile")
        return
    
    try:
        product = msg.text.split(maxsplit=1)[1]
    except:
        await msg.answer("Требуется формат: /log_food <продукт>")
        return
    
    info = fetch_food(product)
    if not info or info["kcal"] == 0:
        await msg.answer("Продукта нет в базе")
        return

    await state.update_data(food=info)
    await msg.answer(
        f"{info['title']} — {info['kcal']} ккал на 100 г\n"
        f"Вес (грамм)?"
    )
    await state.set_state(food_flow.grams)


@dp.message(food_flow.grams)
async def finish_food(msg: Message, state: FSMContext):
    uid = msg.from_user.id
    grams = int(msg.text)
    data = await state.get_data()
    kcal = data["food"]["kcal"] * grams / 100
    user = storage[uid]
    user["cal_now"] += kcal
    user["cal_history"].append(user["cal_now"])

    await state.clear()
    await msg.answer(f"+{kcal:.1f} ккал")

@dp.message(Command("log_workout"))
async def workout(msg: Message):
    uid = msg.from_user.id
    if uid not in storage:
        await msg.answer("Требуется настроить профиль: /set_profile")
        return

    try:
        _, name, minutes = msg.text.split()
        minutes = int(minutes)
    except:
        await msg.answer("Требуется формат: /log_workout <тип> <мин>")
        return

    burned = minutes * 10
    extra_water = (minutes // 30) * 200
    user = storage[uid]
    user["burned"] += burned
    user["water_goal"] += extra_water

    await msg.answer(f"{name} {minutes} мин\n-{burned} ккал")

@dp.message(Command("check_progress"))
async def progress(msg: Message):
    uid = msg.from_user.id
    if uid not in storage:
        await msg.answer("Требуется настроить профиль: /set_profile")
        return
    u = storage[uid]
    water_left = max(u["water_goal"] - u["water_now"], 0)
    cal_balance = u["cal_goal"] - u["cal_now"] + u["burned"]

    await msg.answer(
        f"Вода:\n"
        f"- Выпито: {u['water_now']} / {u['water_goal']} мл\n"
        f"- Осталось: {water_left} мл\n\n"
        f"Калории:\n"
        f"- Потреблено: {int(u['cal_now'])} / {int(u['cal_goal'])}\n"
        f"- Сожжено: {u['burned']} ккал\n"
        f"- Осталось: {int(cal_balance)} ккал"
    )

@dp.message(Command("show_graphs"))
async def graphs(msg: Message):
    uid = msg.from_user.id
    if uid not in storage:
        await msg.answer("Требуется настроить профиль: /set_profile")
        return
    u = storage[uid]
    if not u["water_history"] and not u["cal_history"]:
        await msg.answer("Нет данных для графиков")
        return

    plt.figure()
    plt.plot(u["water_history"], marker="o")
    plt.title("Вода")
    buf = io.BytesIO()
    plt.savefig(buf, format="png")
    plt.close()
    buf.seek(0)

    await msg.answer_photo(
        photo=BufferedInputFile(buf.getvalue(), filename="water.png")
    )

    if u["cal_history"]:
        plt.figure()
        plt.plot(u["cal_history"], marker="o", color="orange")
        plt.title("Калории")
        buf = io.BytesIO()
        plt.savefig(buf, format="png")
        plt.close()
        buf.seek(0)
        
        await msg.answer_photo(
            photo=BufferedInputFile(buf.getvalue(), filename="calories.png")
        )

async def main():
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())