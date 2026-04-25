###################################################################################
#
#    Copyright (C) 2020 Cetmix OÜ
#
#    This program is free software: you can redistribute it and/or modify
#    it under the terms of the GNU LESSER GENERAL PUBLIC LICENSE as
#    published by the Free Software Foundation, either version 3 of the
#    License, or (at your option) any later version.
#
#    This program is distributed in the hope that it will be useful,
#    but WITHOUT ANY WARRANTY; without even the implied warranty of
#    MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#    GNU LESSER GENERAL PUBLIC LICENSE for more details.
#
#    You should have received a copy of the GNU LESSER GENERAL PUBLIC LICENSE
#    along with this program.  If not, see <http://www.gnu.org/licenses/>.
#
###################################################################################

# Used to render dates in html ListView
def get_month(env):
    return {
        1: env._("Jan"),
        2: env._("Feb"),
        3: env._("Mar"),
        4: env._("Apr"),
        5: env._("May"),
        6: env._("Jun"),
        7: env._("Jul"),
        8: env._("Aug"),
        9: env._("Sep"),
        10: env._("Oct"),
        11: env._("Nov"),
        12: env._("Dec"),
    }


BLOCK_QUOTE = (
    "<p><br/></p>"
    "<br/>"
    "<blockquote>----- Original message ----- <br/> Date: %(date)s <br/>"
    " From: %(author)s <br/> Subject: %(subject)s <br/><br/>%(body)s</blockquote>"
)

DEFAULT_SIGNATURE_LOCATION = "a"
