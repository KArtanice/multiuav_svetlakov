# Правки плагина Cosys-AirSim 3.5.0 для MultiUAV

Плагин лежит в проекте Unreal, а не в этом репозитории
(`~/Downloads/Blocks 5.8/Plugins/AirSim`), поэтому правки хранятся здесь патчами.
Пути в патчах — от корня плагина (`Plugins/AirSim`).

| Патч | Что меняет | Зачем | Нужен? |
|---|---|---|---|
| `01-rpc-server-threads.patch` | `Source/SimMode/SimModeBase.cpp`: потоков RPC-сервера `число дронов × 2 + 16` вместо `+ 4` | Каждая команда `moveBy…Async` держит поток сервера до следующей. С окном камер (`multiuav cameras`) свободных потоков не оставалось, и шаг управления растягивался с 54 до 277 мс — пульт запаздывал. С патчем — 53 мс | **Да**, если используется окно камер |
| `02-fast-model.patch` | `AirSimSettings.hpp` (ключ `"Model"` у дрона), `SimpleFlightQuadXParams.hpp` (тяга ×1,3), `SimpleFlightApi.hpp` (наклон до 45°, вращение до 5 рад/с) | Экспериментальная быстрая модель, включается `"Model": "Fast"` в settings.json (`model: fast` в сценарии) | Нет: **нестабильна**, регуляторы SimpleFlight под неё не настроены. Без `"Model": "Fast"` ничего не меняет |

Подробности и замеры — `docs/MultiUAV-Cosys-UE5_Ubuntu22_experience.md`, разделы 18 и 20.

## Наложить

```bash
cd "$HOME/Downloads/Blocks 5.8/Plugins/AirSim"
patch -p1 < ~/Documents/multiuav_svetlakov/airsim_patches/01-rpc-server-threads.patch
patch -p1 < ~/Documents/multiuav_svetlakov/airsim_patches/02-fast-model.patch   # по желанию
```

Затем закрыть Unreal и пересобрать (UBA должен быть отключён, см. раздел 7 файла опыта):

```bash
~/Downloads/UnrealEngine5/Engine/Build/BatchFiles/Linux/Build.sh BlocksEditor Linux Development -Project="$HOME/Downloads/Blocks 5.8/Blocks.uproject"
```

## Снять

```bash
cd "$HOME/Downloads/Blocks 5.8/Plugins/AirSim"
patch -p1 -R < ~/Documents/multiuav_svetlakov/airsim_patches/02-fast-model.patch
patch -p1 -R < ~/Documents/multiuav_svetlakov/airsim_patches/01-rpc-server-threads.patch
```

и пересобрать так же. На этой машине рядом с изменёнными файлами лежат и исходные копии:
`*.bak-before-rpc-threads`, `*.bak-before-fast-model`.

Патчи сняты с Cosys-AirSim 3.5.0 (релиз `5.8-v3.5.0`); на другой версии плагина могут не наложиться.
