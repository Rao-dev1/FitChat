"""Approximate dietary fibre. Ingredients: grams per 100 g as eaten. Foods: grams per serving as listed in foods.py.
Typical values from standard food tables (IFCT / USDA); real values vary with variety and cooking."""

INGREDIENT_FIBRE_100G = {
    "Rajma, boiled": 6.4, "Rajma, dry": 25, "Chickpeas, boiled": 7.6, "Chickpeas, dry": 17,
    "Moong, whole boiled": 7.6, "Moong, dry": 16, "Dal, boiled": 2.5, "Toor dal, dry": 15, "Masoor dal, dry": 11,
    "Chana dal, dry": 15, "Urad dal, dry": 18, "Soya chunks, dry": 13, "Soya chunks, boiled": 4,
    "Green peas, boiled": 5.5, "Tofu": 0.9, "Sattu": 15, "Roasted chana": 17,
    "Rice, cooked": 0.4, "Rice, dry": 1.3, "Brown rice, cooked": 1.8, "Roti, plain": 3.8, "Wheat flour (atta)": 11,
    "Oats, dry": 10, "Poha, dry": 1.5, "Semolina (sooji), dry": 3, "Besan (gram flour)": 10,
    "Bread, whole wheat": 6, "Bread, white": 2.5, "Pasta, cooked": 1.8, "Pasta, dry": 3.2,
    "Potato, boiled": 1.8, "Sweet potato, boiled": 2.5, "Makhana": 8,
    "Honey": 0.2, "Peanuts": 8.5, "Peanut butter": 6, "Almonds": 12.5, "Cashews": 3.3, "Walnuts": 6.7,
    "Chia seeds": 34, "Flax seeds": 27, "Coconut, grated": 9,
    "Onion": 1.7, "Tomato": 1.2, "Spinach": 2.2, "Cauliflower": 2, "Cabbage": 2.5, "Carrot": 2.8, "Cucumber": 0.5,
    "Brinjal": 3, "Okra": 3.2, "Capsicum": 1.7, "Broccoli": 2.6, "Mushroom": 1, "Green beans": 2.7,
    "Bottle gourd": 0.5, "Mixed vegetables": 3,
    "Banana": 2.6, "Apple": 2.4, "Orange": 2.4, "Mango": 1.6, "Papaya": 1.7, "Watermelon": 0.4, "Guava": 5.4,
    "Pomegranate": 4, "Grapes": 0.9, "Dates, dried": 7,
}  # anything not listed (milk, eggs, meat, oils, sugar, ...) has no fibre

FOOD_FIBRE_PER_SERVING = {
    "Roti": 1.5, "Plain paratha": 2, "Aloo paratha": 3, "Steamed rice": 0.6, "Dal": 4, "Rajma curry": 6, "Chole": 7,
    "Boiled chickpeas": 7.6, "Moong sprouts": 2, "Paneer bhurji": 1, "Chicken curry": 1, "Fish curry": 1,
    "Soya chunks": 4, "Oats": 4, "Poha": 2, "Upma": 2.5, "Idli": 0.5, "Plain dosa": 1, "Sambar": 3,
    "Mixed veg sabzi": 4, "Bhindi": 3.5, "Brown bread": 2, "Peanuts": 2.5, "Almonds": 1.3, "Peanut butter": 1,
    "Banana": 3.1, "Apple": 4.4,
}
