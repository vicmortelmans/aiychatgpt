#!/usr/bin/env python3
import argparse
from dotenv import load_dotenv
import getpass
import locale
import logging
import os
from queue import Queue
from sys import stdout
from threading import Thread, Lock
import uuid

from google.cloud import texttospeech

from util import Button, Led
#from aiy.voice import tts
from aiy.cloudspeech import CloudSpeechClient
# to make this work, a change of the aiy module was needed
# in cloudspeech.py, the hardcoded settings of the audio device are configured
# to match the AIY Voice HAT, but I'm using some cheap USB audio adapter now
# AUDIO_SAMPLE_RATE_HZ = 48000
# AUDIO_FORMAT=AudioFormat(sample_rate_hz=AUDIO_SAMPLE_RATE_HZ,
#                          num_channels=1,
#                          bytes_per_sample=2)

from openai import OpenAI

role = "Je bent een stemgestuurde assistent die graag nieuwe onderwerpen in het gesprek brengt." 

logger = logging.getLogger("aichatgpt")
handler = logging.StreamHandler(stdout)
handler.setFormatter(logging.Formatter(fmt='%(asctime)s,%(msecs)d %(levelname)-8s [%(filename)s:%(lineno)d %(funcName)s] %(message)s', datefmt='%Y-%m-%d:%H:%M:%S'))
logger.addHandler(handler)
logger.setLevel(logging.DEBUG)

load_dotenv(os.getenv('HOME') + "/.env")  # contains OPENAI_API_KEY
AI = OpenAI()
tts_client = texttospeech.TextToSpeechClient()
sentences_text = Queue()
sentences_mp3 = Queue()
lock = Lock()
ai_working = False

def converter():
    while True:
        # wait until a new sentence is added to the queue
        sentence_text = sentences_text.get()
        logger.info(f"Converting '{sentence_text}' to mp3")
        sentence_mp3 = f"/tmp/{str(uuid.uuid4())}.mp3"
        synthesis_input = texttospeech.SynthesisInput(text=sentence_text)
        voice = texttospeech.VoiceSelectionParams(language_code="nl-BE")
        audio_config = texttospeech.AudioConfig(audio_encoding=texttospeech.AudioEncoding.MP3)
        response = tts_client.synthesize_speech(input=synthesis_input, voice=voice, audio_config=audio_config)
        logger.info(f"Storing '{sentence_text}' as {sentence_mp3}")
        with open(sentence_mp3, "wb") as out:
            out.write(response.audio_content)
        sentences_mp3.put(sentence_mp3)

def speaker():
    while True:
        # wait until a new mp3 is added to the queue
        sentence_mp3 = sentences_mp3.get()
        logger.info(f"Speaking {sentence_mp3}")
        os.system(f"mpg123 -q {sentence_mp3}") 
        os.remove(sentence_mp3)
        if sentences_mp3.empty() and sentences_text.empty() and not ai_working: 
            logger.info("Speech is finished completely")
            lock.release()

def main():
    logger.info(f"Running as {getpass.getuser()}")

    client = CloudSpeechClient()

    converter_thread = Thread(target=converter)
    speaker_thread = Thread(target=speaker)
    converter_thread.start()
    speaker_thread.start()

    messages = [
        {"role": "system", "content": role}
    ] 

    times_hearing_nothing = 0

    with Led(channel=17) as led, Button(channel=27) as button:
        while True:
            lock.acquire()
            if times_hearing_nothing > 3:
                logger.info("Silence... resetting conversation and waiting for button to start listening again")
                times_hearing_nothing = 0
                # reset conversation
                messages = [
                    {"role": "system", "content": role}
                ] 
                button.wait_for_press()
            led.state = Led.ON
            logger.info("Start listening")
            text = client.recognize(language_code="nl")
            led.state = Led.OFF
            if text is None:
                logger.info('You said nothing.')
                times_hearing_nothing += 1
                lock.release()
                continue

            logger.info('You said: "%s"' % text)

            messages.append({"role": "user", "content": text})

            ai_working = True
            completion = AI.chat.completions.create(
              model="gpt-3.5-turbo",
              messages=messages,
              stream=True
            )

            answer = ""

            for chunk in completion:
                if chunk.choices[0].delta.content == None:
                    # no more content; answer is complete
                    sentences_text.put(answer)
                    ai_working = False
                    break
                answer += chunk.choices[0].delta.content
                if ". " in answer:
                    # submit finished sentence for converting and speaking
                    (sentence, answer) = answer.split(". ", maxsplit=1)
                    sentences_text.put(sentence)

            logger.info(f"Adding answer to conversation: '{answer}'")
            messages.append({"role": "assistant", "content": answer})


if __name__ == '__main__':
    main()
