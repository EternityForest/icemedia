import os
import time
import sys
import icemedia.sound_player

testmedia = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "Brothers Unite.opus"
)

icemedia.sound_player.play_sound(testmedia)
time.sleep(3)
sys.exit()
