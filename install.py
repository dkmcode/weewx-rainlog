# installer for Rainlog

from setup import ExtensionInstaller

def loader():
    return RainlogInstaller()

class RainlogInstaller(ExtensionInstaller):
    def __init__(self):
        super(RainlogInstaller, self).__init__(
            version="0.1",
            name='rainlog',
            description='Upload rain data to rainlog.org',
            author="David Malick",
            config={
                'StdRESTful': {
                    'Rainlog' : {
                        'username': 'USERNAME',
                        'password': 'PASSWORD'
                    }
                }
            },
            files=[('bin/user', ['bin/user/rainlog.py']),
                   ('archive',[])
                   ],
            restful_services='user.rainlog.StdRainlog'
        )
