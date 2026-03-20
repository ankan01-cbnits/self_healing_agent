from playwright.sync_api import Page

class UserCredential:
    def __init__(self, page: Page):
        self.page = page
        self.first = "#first-name"
        self.last = "#last-name"
        self.pincode = "#postal"
        self.continuous="#continue"

    def user_data(self,first:str,last:str,pincode:str):
        self.page.fill(self.first, first)
        self.page.fill(self.last, last)
        self.page.fill(self.pincode, pincode)
        self.page.wait_for_timeout(1000)
    def click_conti(self):
        self.page.click(self.continuous)
