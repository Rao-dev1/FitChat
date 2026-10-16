"""Starter table of common Indian foods. VALUES ARE APPROXIMATE (typical home-style servings).
Check against package labels / IFCT and edit to match how YOU cook and serve. Format:
(name, aliases, serving, kcal, protein_g, carbs_g, fat_g)"""

FOODS = [
    ("Roti", ["chapati", "phulka"], "1 medium (40 g)", 110, 3.3, 20, 2),
    ("Plain paratha", ["paratha"], "1 medium", 200, 4, 30, 7),
    ("Aloo paratha", [], "1 medium", 290, 6, 40, 12),
    ("Steamed rice", ["rice", "chawal"], "1 cup cooked (150 g)", 200, 4, 44, 0.4),
    ("Dal", ["toor dal", "dal tadka", "varan"], "1 katori (150 g)", 150, 8, 22, 3),
    ("Rajma curry", ["rajma masala", "rajma sabji", "rajma sabzi"], "1 katori (150 g)", 170, 8, 25, 4),
    ("Chole", ["chana masala"], "1 katori (150 g)", 200, 9, 28, 6),
    ("Boiled chickpeas", ["boiled chana", "kala chana"], "1 katori (100 g)", 164, 8.9, 27, 2.6),
    ("Moong sprouts", ["sprouts"], "1 katori (100 g)", 100, 7, 17, 0.6),
    ("Paneer", ["cottage cheese"], "100 g", 265, 18, 3, 20),
    ("Paneer bhurji", [], "1 katori (100 g)", 250, 14, 6, 18),
    ("Curd", ["dahi", "yogurt"], "1 katori (100 g)", 60, 3.5, 4.7, 3.3),
    ("Chaas", ["buttermilk"], "1 glass", 40, 2, 3, 1.5),
    ("Milk", ["toned milk", "doodh"], "1 glass (250 ml)", 145, 8, 12, 7.5),
    ("Boiled egg", ["egg", "anda"], "1 large", 78, 6.3, 0.6, 5.3),
    ("Omelette", [], "2 eggs", 190, 13, 1, 15),
    ("Chicken breast", ["grilled chicken", "boiled chicken"], "100 g cooked", 165, 31, 0, 3.6),
    ("Chicken curry", [], "1 katori (150 g)", 220, 18, 6, 14),
    ("Fish curry", ["fish"], "1 katori (150 g)", 200, 20, 5, 11),
    ("Soya chunks", ["nutrela", "soy chunks"], "30 g dry", 104, 15.6, 9.9, 0.2),
    ("Whey protein", ["protein shake", "whey"], "1 scoop (30 g)", 120, 24, 3, 1.5),
    ("Oats", ["oatmeal"], "40 g dry", 156, 6.8, 26.5, 2.8),
    ("Poha", [], "1 plate", 270, 5, 45, 8),
    ("Upma", [], "1 plate", 250, 6, 38, 8),
    ("Idli", [], "1 piece", 58, 2, 12, 0.4),
    ("Plain dosa", ["dosa"], "1 piece", 130, 3, 22, 3),
    ("Sambar", [], "1 katori (150 g)", 90, 4, 13, 2.5),
    ("Mixed veg sabzi", ["sabzi", "bhaji"], "1 katori (100 g)", 110, 3, 12, 6),
    ("Bhindi", ["okra"], "1 katori (100 g)", 100, 2.5, 9, 6.5),
    ("Brown bread", ["bread"], "1 slice (30 g)", 70, 3, 12, 1),
    ("Peanuts", ["groundnuts", "shengdana"], "30 g", 170, 7.7, 4.8, 14.7),
    ("Almonds", ["badam"], "10 pieces", 70, 2.6, 2.5, 6),
    ("Peanut butter", [], "1 tbsp (16 g)", 94, 4, 3, 8),
    ("Banana", ["kela"], "1 medium", 105, 1.3, 27, 0.4),
    ("Apple", [], "1 medium", 95, 0.5, 25, 0.3),
]

# Starter foods that were renamed: old name -> new name (applied to untouched starter rows only).
RENAMED = {"Rajma": "Rajma curry"}

# Corrected starter values: applied to untouched starter rows (source seed_approx) on existing databases.
VALUE_FIXES = {"Oats": (156, 6.8, 26.5, 2.8)}
