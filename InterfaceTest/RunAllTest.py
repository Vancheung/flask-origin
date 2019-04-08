import unittest
import Webapps

class TestWebapps(unittest.TestCase):

    def test_index(self):
        rv = self.app.get('/index')
        print(rv)
        #assert "Hello world" in rv

    def test_index_username(self):
        rv = self.app.get('/user/testuser1')
        print(rv)
        #assert "Hello world" in rv

    def setUp(self):
        print("Start Server.......")
        self.app = Webapps.app.test_client()

if __name__ == "__main__":
    unittest.main()
