import requests
from datetime import datetime, timezone
import time
import schedule
from PIL import Image, ImageFilter
import urllib
import logging
import boto3
from botocore.exceptions import ClientError
import os
from bs4 import BeautifulSoup
from pushover import Pushover

# Constants and Configuration
SERVICE_NAME = "Notion TV"
NOTION_TOKEN = os.getenv("NOTION_TOKEN")
DATABASE_ID = os.getenv("NOTION_DATABASE_ID")

USE_PUSHOVER = os.getenv("USE_PUSHOVER", "no")  # Default to 'no' if USE_PUSHOVER is not set
USE_AWS = os.getenv("USE_AWS", "no")  # Default to 'no' if USE_AWS is not set
BUCKET = os.getenv("AWS_BUCKET")

if USE_AWS.lower() == "yes":
    BUCKET = os.getenv("AWS_BUCKET")

if USE_PUSHOVER.lower() == "yes":
    PO_USER = os.getenv("PO_USER")
    PO_TOKEN = os.getenv("PO_TOKEN")
    po = Pushover(PO_TOKEN)
    po.user(PO_USER)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    handlers=[logging.StreamHandler()],
)

NOTION_headers = {
    "Authorization": "Bearer " + NOTION_TOKEN,
    "Content-Type": "application/json",
    "Notion-Version": "2022-06-28",
}

def send_push(subject,message):
  msg = po.msg(message)
  msg.set("title", subject)
  po.send(msg)

def status():
    current_time = str(datetime.now())
    subject = SERVICE_NAME + " is online"
    message = SERVICE_NAME + " is online and running at " + current_time
    send_push(subject,message)

def remove_html(input_string):
    soup = BeautifulSoup(input_string, "html.parser")
    return soup.get_text()

def upload_file(file_name,object_name):
    # print("Start File Uplaod")
    # If S3 object_name was not specified, use file_name
    if object_name is None:
        object_name = os.path.basename(file_name)
    # Upload the file
    s3_client = boto3.client('s3')
    try:
        response = s3_client.upload_file(file_name, BUCKET, object_name)
        print(response)
    except ClientError as e:
        logging.error(e)
        print.error(e)
        return False
    return True

def get_tv_by_name(new_tv_title):
    # print("TV Title for API: "+new_tv_title)
    base_url = 'https://api.tvmaze.com/singlesearch/shows?q='+new_tv_title
    # print(base_url)
    try:
        response = requests.get(base_url)
        print(response)
        response.raise_for_status()
        tv_data = response.json()
        return tv_data
    except requests.exceptions.RequestException as e:
        print(f"Error: {e}")
        return None

def get_tv_by_id(tv_id):
    tv_id = str(tv_id)
    base_url = 'https://api.tvmaze.com/shows/'+tv_id
    # print(base_url)
    try:
        response = requests.get(base_url)
        response.raise_for_status()
        tv_data = response.json()
        return tv_data
    except requests.exceptions.RequestException as e:
        print(f"Error: {e}")
        return None

def get_seasons(tv_id):
    tv_id = str(tv_id)
    base_url = 'https://api.tvmaze.com/shows/'+tv_id+'/seasons'
    # print("Extended Series Details: "+base_url)
    try:
        response = requests.get(base_url)
        print(response)
        response.raise_for_status()
        tv_data = response.json()
        # print("Print Extended Details: ")
        print(tv_data)
        return tv_data
    except requests.exceptions.RequestException as e:
        print(f"Error: {e}")
        return None

def get_pages(num_pages=None):
    """
    If num_pages is None, get all pages, otherwise just the defined number.
    """
    url = f"https://api.notion.com/v1/databases/{DATABASE_ID}/query"
    get_all = num_pages is None
    page_size = 100 if get_all else num_pages
    payload = {"page_size": page_size}
    response = requests.post(url, json=payload, headers=NOTION_headers)
    data = response.json()
    results = data["results"]
    while data["has_more"] and get_all:
        payload = {"page_size": page_size, "start_cursor": data["next_cursor"]}
        url = f"https://api.notion.com/v1/databases/{DATABASE_ID}/query"
        response = requests.post(url, json=payload, headers=NOTION_headers)
        data = response.json()
        results.extend(data["results"])
    return results

def new_ep_check():
   pages = get_pages()
   for page in pages:
      try:
         page_id = page["id"]
         props = page["properties"]
         tv_id = props["tvmazeID"]["number"]
         title = props["Name"]["title"][0]["text"]["content"]
         last_id = props["Last Aired Episode"]["number"]
         tv_data = get_tv_by_id(tv_id)
         last_episode = tv_data['_links']['previousepisode']['href']
         last_episode = last_episode.split("/episodes/")[-1]
         last_episode = int(last_episode)
         
         if last_id != last_episode:
            print("New epsiode of "+title+" is schedule. We need to update!")
            update_tv_data(tv_data,page_id)
      except KeyError as e:
         print(f"Error processing page {page['id']}: {e} key not found.")

def read_pages():
   pages = get_pages()
   for page in pages:
      try:
         page_id = page["id"]
         props = page["properties"]
         title = props["Name"]["title"][0]["text"]["content"]
         tvmazeID = props["tvmazeID"]["number"]
         # last_id = props["Last Aired Episode"]["number"]
         #print("TV: ", title, page_id, last_id)

         if tvmazeID is None:
            new_tv_title = title.replace(';', '')
            new_tv_title = new_tv_title.replace(' ', '+')
            tv_data = get_tv_by_name(new_tv_title)
            update_tv_data(tv_data,page_id)
      except KeyError as e:
         print(f"Error processing page {page['id']}: {e} key not found.")
         subject = "Error reading data from Notion for "+title
         message = e
         send_push(subject,message)

def update_page(page_id: str, data: dict):
    print("Start Update_Page function")
    url = f"https://api.notion.com/v1/pages/{page_id}"
    print(url)
    payload = data
    print(payload)
    res = requests.patch(url, json=payload, headers=NOTION_headers)
    if res.status_code == 200:
        print('Book details updated successfully!')
    else:
        print(f'Notion update request failed with status code: {res.status_code}')

        json_data = json.loads(res.content.decode('utf-8'))
        # Print key-value pairs
        for key, value in json_data.items():
          # print(f'{key}: {value}')
          subject = json_data['status'],json_data['code']
          message = json_data['message']
          send_push(subject,message)
    return res

def make_banner(img_url,page_id):
   # sizing from each image "_V1_SX300."
   img_name = str(page_id+".jpg")
   urllib.request.urlretrieve(img_url,img_name) 
   
   img = Image.open(img_name) 
   width, height = img.size 

   new_height = 600
   new_width  = new_height * width / height

   postersize = (int(new_width), new_height)
   img_poster = img.resize(postersize)
   # img_poster.show()

   left = 5
   top = height / 3
   right = width
   bottom = 2 * height / 3
   
   # Cropped image of above dimension
   img = img.crop((left, top, right, bottom))
   newsize = (1500, 600)
   img_banner = img.resize(newsize)
   img_banner = img_banner.filter(ImageFilter.BoxBlur(30))
   # img_banner.show()

   background = img_banner
   foreground = img_poster
   background.paste(foreground, (514,0)) 
   background.save(img_name)
   upload_file(img_name,img_name)
   # background.show()
   return background

def update_tv_data(tv_data,page_id):
      print("Start TV Update")
      #  tv_data = get_tv_by_name(new_tv_title)
      img_url = tv_data['image']['original']
      thetvdb = tv_data['externals']['thetvdb']
      tv_id = tv_data['id']
      status = tv_data['status']
      name = tv_data['name']
      if tv_data['premiered'] is None:
          premiered = tv_data['premiered']
      else:
          premiered = {"start":tv_data['premiered']}
      if tv_data['ended'] is None:
          ended = tv_data['ended']
      else:
          ended = {"start":tv_data['ended']}
      last_episode = tv_data['_links']['previousepisode']['href']
      last_episode = last_episode.split("/episodes/")[-1]
      last_episode = int(last_episode)
      summary = remove_html(tv_data['summary'])
      season_data = get_seasons(tv_id)
      season_count = sum("episodeOrder" in item for item in season_data)
      total_episodes = sum(item["episodeOrder"] for item in season_data if "episodeOrder" in item and item["episodeOrder"] is not None)
      make_banner(img_url,page_id)
      banner = "https://pipedream-api.s3.us-east-2.amazonaws.com/"+page_id+".jpg"
      
      # print("Build Notion Update")
      update_data = {
      "cover":{
         "external":{
            "url":banner
         }
      },
      "properties": {
        "TVDBID": {
            "number": thetvdb
        },
        "tvmazeID": {
            "number": tv_id
        },
        "Show Status": {
            "select": {
                "name": status
            }
        },
        "Premiered":{
            "type":"date",
            "date": premiered
        },
        "Ended": {
            "type": "date",
            "date": ended
        },
        "Last Aired Episode": {
            "type": "number",
            "number": last_episode
        },
        "Seasons": {
            "number": season_count
        },
         "Poster":{
            "type":"files",
            "files":[
               {
                  "name":"Title",
                  "type":"external",
                  "external":{
                     "url":img_url
                  }
               }
            ]
         },
        "Total Eps.": {
            "number": total_episodes
        },
         "Summary":{
            "type":"rich_text",
            "rich_text":[
               {
                  "type":"text",
                  "text":{
                     "content":summary
                  }
               }
            ]
         },
        "Name": {
            "type": "title",
            "title": [
                {
                    "type": "text",
                    "text": {
                        "content": name
                  }
               }
            ]
         }
      }
   }

      # print("Now Update the page in Notion")
      update_page(page_id,update_data)
      os.remove(page_id+".jpg")

schedule.every(60).seconds.do(read_pages)
schedule.every().sunday.do(new_ep_check) 
logging.info("Next scan scheduled...")

while True:
    schedule.run_pending()
    time.sleep(1)
    

