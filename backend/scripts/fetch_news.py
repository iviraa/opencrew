from app.storm import news

if __name__ == "__main__":
    print("articles", news.collect_replay())  # hourly GDELT GKG samples + article text, cached under data/raw/helene/news
