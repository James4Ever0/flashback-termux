su -c 'pm path com.android.chrome'
# select the first line
# package:/data/app/~~pvLiFdaVguSW8iXCBmprwA==/com.android.chrome-0v7sk4dmLo_EMSfP0CuKYQ==/base.apk
# copy the first apk
su -c 'cp /data/app/~~pvLiFdaVguSW8iXCBmprwA==/com.android.chrome-0v7sk4dmLo_EMSfP0CuKYQ==/base.apk chrome.apk'
# remember to change own to current user, use a python managed temporary directory context manager, cleanup the directory after exiting the context.
aapt dump badging chrome.apk | grep 'application-label:'
# application-label:'Chrome'
