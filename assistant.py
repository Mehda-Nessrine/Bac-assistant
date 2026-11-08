"""Glue between loader, router and generator. No UI code here, so any front-end
(Gradio, Telegram, an API...) can reuse it."""
import config
import generator
import loader
import router


class Assistant:
    def __init__(self, client=None, loaded=None):
        self.loaded = loaded or loader.load_all()
        if client is None:
            from google import genai
            client = genai.Client(api_key=config.get_api_key())
        self.client = client

    def reload_data(self):
        """Re-scan DATA_DIR (cheap when nothing changed thanks to the cache fingerprint)."""
        self.loaded = loader.load_all()
        return self.loaded

    def ask(self, question, history, mode="full", last_ids=None):
        """Returns (route, answer). Never raises."""
        r = router.route(question, history, self.loaded, self.client, last_ids=last_ids)
        a = generator.generate(r, self.loaded, self.client, mode=mode, history=history)
        return r, a

    def full_solution(self, route, history):
        """Same request as before but in full mode, reusing the router's decision (1 API call)."""
        return generator.generate(route, self.loaded, self.client, mode="full", history=history)
