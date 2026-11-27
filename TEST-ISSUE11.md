# Tester l’issue #11 sur Windows

1. Extrais le ZIP sur un volume NTFS et lance **Test-Issue11.bat**.
2. Choisis **A**, puis le dossier qui contient déjà `Orbitals.exe`, `Orbitals_code.dll` et `Orbitals_data`. Le jeu se lance avec
   le runtime du kit et réutilise le module compatible. Utilise Liftoff pour mettre à jour le module si le test le demande. Le premier lancement peut préparer les shaders.
3. Rejoue le passage co-op où les FPS baissent. Joue environ 30 secondes dans la même zone après stabilisation, puis quitte le jeu normalement.
4. Répète le passage avec **B** et le même dossier. **C** teste ensuite l’effet de l’attente ciblée par rapport à B.
5. Le dossier **issue11-results** s’ouvre sur le résultat de chaque passage. Garde **Orbitals.log**, **frames.csv** et **test.json** avec le nom du checkpoint.

- **A** utilise la traduction NVN synchrone, comme le profil 30 FPS de référence.
- **B** utilise la traduction NVN asynchrone avec le comportement habituel des attentes.
- **C** utilise la traduction asynchrone et limite l’attente à la fence demandée, comme le mode B de la preview.6.

Les trois modes conservent la même cadence et les mêmes réglages graphiques. Pour diagnostiquer la scène, refais un passage et appuie sur **F6** une fois en jeu au moment du ralentissement. Attends quelques secondes avant de quitter. Le résultat inclut un fichier `swr_trace_*.json` qui détaille la traduction des commandes, l’envoi à Vulkan et la complétion des fences sur 36 images. Mesure les FPS sur les passages effectués sans F6.

À la première sélection du jeu, le test copie les réglages et la sauvegarde du profil Liftoff reconnu, ou utilise la sauvegarde de
l’installation et l’INI existant. Les essais suivants repartent de cette copie et utilisent un cache partagé dans le dossier du kit.
Pour refaire la copie depuis un autre checkpoint de la sauvegarde d’origine, extrais le ZIP dans un nouveau dossier.
